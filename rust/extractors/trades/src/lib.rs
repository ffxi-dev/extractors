//! items/trades.py, line for line: each trade the character made to an NPC (c2s 0x036), its items as the
//! world's inventory holds them, and the event or message the NPC answered with. Its Python twin keeps the
//! docs.

use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::{C2S, Decoded, Field, Packet, S2C, World, row};

/// The NPC's event or message this soon after a trade answers it.
const ANSWER_MS: i64 = 5000;
/// The inventory's slot 0 holds the gil.
const GIL_SLOT: i64 = 0;

macro_rules! fields {
    ($dir:expr, $op:expr; $($path:literal),*) => { [$(Field::new($dir, $op, $path)),*] };
}

/// c2s 0x036: UniqueNo, ActIndex, ItemNum.
static TRADE: [Field; 3] = fields!(C2S, 0x036; "UniqueNo", "ActIndex", "ItemNum");
static SLOT: [Field; 10] = fields!(C2S, 0x036; "PropertyItemIndexTbl[0]", "PropertyItemIndexTbl[1]",
    "PropertyItemIndexTbl[2]", "PropertyItemIndexTbl[3]", "PropertyItemIndexTbl[4]", "PropertyItemIndexTbl[5]",
    "PropertyItemIndexTbl[6]", "PropertyItemIndexTbl[7]", "PropertyItemIndexTbl[8]", "PropertyItemIndexTbl[9]");
static COUNT: [Field; 10] = fields!(C2S, 0x036; "ItemNumTbl[0]", "ItemNumTbl[1]", "ItemNumTbl[2]",
    "ItemNumTbl[3]", "ItemNumTbl[4]", "ItemNumTbl[5]", "ItemNumTbl[6]", "ItemNumTbl[7]", "ItemNumTbl[8]",
    "ItemNumTbl[9]");
/// The NPC's answers: (UniqueNo, EventPara) of 0x032 to 0x034, (UniqueNo, MesNum) of 0x036 and 0x02A.
static ANSWER: [[Field; 2]; 5] = [
    fields!(S2C, 0x032; "UniqueNo", "EventPara"),
    fields!(S2C, 0x033; "UniqueNo", "EventPara"),
    fields!(S2C, 0x034; "UniqueNo", "EventPara"),
    fields!(S2C, 0x036; "UniqueNo", "MesNum"),
    fields!(S2C, 0x02A; "UniqueNo", "MesNum"),
];

pub static META: Meta = Meta {
    name: "trades",
    version: 1,
    reads: &[(C2S, 0x036), (S2C, 0x032), (S2C, 0x033), (S2C, 0x034), (S2C, 0x036), (S2C, 0x02A)],
    sparse: true,
    tables: &[Table {
        name: "trades",
        columns: &[
            ("npc_id", I64),
            ("npc_index", I32),
            ("item_ids", ListI32),
            ("quantities", ListI64),
            ("slots", ListI32),
            ("gil", I64),
            ("event_id", I32),
            ("event_idx", I64),
            ("message", I32),
            ("zone_id", I32),
        ],
    }],
};

/// The last trade, while the NPC may still answer it.
struct Open {
    id: RowId,
    ts_ms: i64,
    npc: Option<i64>,
    answered: bool,
}

#[derive(Default)]
pub struct Trades {
    open: Option<Open>,
}

impl Extractor for Trades {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        if self.open.as_ref().is_some_and(|o| p.ts_ms - o.ts_ms > ANSWER_MS) {
            self.open = None;
        }
        if p.direction == C2S {
            self.trade(p, f, world, out);
            return;
        }
        let k = &ANSWER[match p.opcode {
            0x032..=0x034 => (p.opcode - 0x032) as usize,
            0x036 => 3,
            _ => 4,
        }];
        let Some(o) = self.open.as_mut().filter(|o| k[0].int(f) == o.npc) else { return };
        if matches!(p.opcode, 0x032..=0x034) {
            out.set(o.id, "event_id", k[1].int(f));
            out.set(o.id, "event_idx", p.idx as i64);
            // The event answers it: a message after is the event's.
            self.open = None;
        } else if !o.answered {
            out.set(o.id, "message", k[1].int(f).unwrap_or(0) & 0x7FFF);
            o.answered = true;
        }
    }
}

impl Trades {
    fn trade(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let (mut items, mut quantities, mut slots, mut gil) = (Vec::new(), Vec::new(), Vec::new(), None);
        for i in 0..TRADE[2].int(f).unwrap_or(0).clamp(0, 10) as usize {
            let (slot, n) = (SLOT[i].int(f), COUNT[i].int(f));
            if slot == Some(GIL_SLOT) {
                gil = Some(gil.unwrap_or(0) + n.unwrap_or(0));
                continue;
            }
            items.push(world.items.get(&(Some(0), slot)).copied().flatten());
            quantities.push(n);
            slots.push(slot);
        }
        let npc = TRADE[0].int(f);
        let id = out.emit(
            "trades",
            Some(p),
            row! {
                npc_id: npc,
                npc_index: TRADE[1].int(f),
                item_ids: items,
                quantities: quantities,
                slots: slots,
                gil: gil,
                zone_id: world.zone,
            },
        );
        self.open = Some(Open { id, ts_ms: p.ts_ms, npc, answered: false });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MapFields, drive};

    const ZONE: i64 = 245;
    const NPC: i64 = 0x0100_0000 | (ZONE << 12) | 100;
    const OTHER: i64 = NPC + 1;
    const STEW: i64 = 4569;
    const ORE: i64 = 643;

    type Step = (u16, MapFields);

    fn held(index: i64, item: i64, count: i64) -> Step {
        (0x020, MapFields::new().int("Category", 0).int("ItemIndex", index).int("ItemNo", item).int("ItemNum", count))
    }

    /// slots: (inventory slot, count); slot 0 is gil.
    fn trade(npc: i64, slots: &[(i64, i64)]) -> Step {
        let mut f =
            MapFields::new().int("UniqueNo", npc).int("ActIndex", npc & 0xFFF).int("ItemNum", slots.len() as i64);
        for (i, &(slot, n)) in slots.iter().enumerate() {
            f = f.int(SLOT[i].path, slot).int(COUNT[i].path, n);
        }
        (0x036, f)
    }

    fn npc(npc: i64, path: &str, v: i64) -> Step {
        (if path == "EventPara" { 0x034 } else { 0x036 }, MapFields::new().int("UniqueNo", npc).int(path, v))
    }

    #[test]
    fn a_trade_names_its_items_from_the_inventory_and_takes_the_npcs_answer() {
        let after = vec![
            trade(NPC, &[(5, 3), (0, 1000)]),
            npc(NPC, "EventPara", 10),           // onTrade's startEvent
            trade(NPC, &[(9, 1), (7, 2)]),       // slot 7 the capture never named
            npc(OTHER, "MesNum", 0x8000 | 6000), // another NPC: no answer
            npc(NPC, "MesNum", 0x8000 | 7000),
            trade(NPC, &[(5, 1)]),
            npc(NPC, "EventPara", 11), // too late: 6 s after
        ];
        let c2s = [true, false, true, false, false, true, false];
        let mut steps = vec![(0x00A, MapFields::new().int("ZoneNo", ZONE)), held(5, STEW, 12), held(9, ORE, 3)];
        steps.extend(after);
        let directions = [S2C; 3].into_iter().chain(c2s.map(|c| if c { C2S } else { S2C })).collect();
        let times = vec![0, 0, 0, 1000, 2000, 10_000, 10_500, 11_000, 20_000, 26_000];
        let o = Drive { times: Some(times), directions: Some(directions), ..Drive::default() };
        let out = drive(&mut Trades::default(), steps, o);
        let r = out.rows("trades");
        let keys = ["item_ids", "quantities", "slots", "gil", "event_id", "message"];
        let got: Vec<Vec<V>> = (0..r.len()).map(|i| keys.iter().map(|k| r.get(i, k)).collect()).collect();
        let ints = |xs: &[Option<i64>]| V::Ints(xs.to_vec());
        assert_eq!(
            got,
            [
                vec![ints(&[Some(STEW)]), ints(&[Some(3)]), ints(&[Some(5)]), V::Int(1000), V::Int(10), V::Null],
                vec![
                    ints(&[Some(ORE), None]),
                    ints(&[Some(1), Some(2)]),
                    ints(&[Some(9), Some(7)]),
                    V::Null,
                    V::Null,
                    V::Int(7000)
                ],
                vec![ints(&[Some(STEW)]), ints(&[Some(1)]), ints(&[Some(5)]), V::Null, V::Null, V::Null],
            ]
        );
        let got: Vec<V> = ["npc_id", "zone_id", "event_idx"].iter().map(|c| r.get(0, c)).collect();
        assert_eq!(got, [NPC, ZONE, 4].map(V::Int));
    }
}
