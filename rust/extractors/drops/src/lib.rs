//! items/drops.py, line for line: each item that entered the treasure pool (0x0D2), and the lot result (0x0D3)
//! that settled it. Its Python twin keeps the docs.

use std::collections::HashMap;

use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

/// 0x0D3 JudgeFlg; 0 is a lot or pass with the slot still open.
fn outcome(judge: Option<i64>) -> Option<&'static str> {
    match judge? {
        1 => Some("won"),
        2 => Some("error"),
        3 => Some("lost"),
        _ => None,
    }
}

static JUDGE: Field = Field::new(S2C, 0x0D3, "JudgeFlg");
static SLOT_0D3: Field = Field::new(S2C, 0x0D3, "TrophyItemIndex");
static WINNER: Field = Field::new(S2C, 0x0D3, "LootUniqueNo");
static WINNER_NAME: Field = Field::new(S2C, 0x0D3, "sLootName");
static LOT: Field = Field::new(S2C, 0x0D3, "LootPoint");
static ITEM: Field = Field::new(S2C, 0x0D2, "TrophyItemNo");
static MOB_ID: Field = Field::new(S2C, 0x0D2, "TargetUniqueNo");
static SLOT_0D2: Field = Field::new(S2C, 0x0D2, "TrophyItemIndex");
static START: Field = Field::new(S2C, 0x0D2, "StartTime");
static QUANTITY: Field = Field::new(S2C, 0x0D2, "TrophyItemNum");
static MOB_INDEX: Field = Field::new(S2C, 0x0D2, "TargetActIndex");
static GOLD: Field = Field::new(S2C, 0x0D2, "Gold");

pub static META: Meta = Meta {
    name: "drops",
    version: 3,
    reads: &[(S2C, 0x0D2), (S2C, 0x0D3)],
    sparse: true,
    tables: &[Table {
        name: "drops",
        columns: &[
            ("item_id", I32),
            ("quantity", I32),
            ("mob_id", I64),
            ("mob_index", I32),
            ("slot", I32),
            ("start_time", I64),
            ("gold", I32),
            ("outcome", Str),
            ("winner_id", I64),
            ("winner_name", Str),
            ("winning_lot", I32),
            ("settled_ms", I64),
            ("settled_idx", I64),
            ("zone_id", I32),
        ],
    }],
};

/// A pool entry: mob, item, slot, start time.
type Entry = (Option<i64>, i64, Option<i64>, Option<i64>);

#[derive(Default)]
pub struct Drops {
    /// Each row, and whether its slot settled.
    rows: Vec<(RowId, bool)>,
    /// entry -> its row
    seen: HashMap<Entry, usize>,
    /// pool slot -> the row its lot result fills in
    open: HashMap<Option<i64>, usize>,
}

impl Extractor for Drops {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        if p.opcode == 0x0D3 {
            let Some(outcome) = outcome(JUDGE.int(f)) else { return };
            if let Some(r) = self.open.remove(&SLOT_0D3.int(f)) {
                let (id, settled) = &mut self.rows[r];
                *settled = true;
                out.set(*id, "outcome", outcome);
                out.set(*id, "winner_id", WINNER.int(f).filter(|&v| v != 0));
                out.set(*id, "winner_name", WINNER_NAME.text(f));
                out.set(*id, "winning_lot", LOT.int(f));
                out.set(*id, "settled_ms", p.ts_ms);
                out.set(*id, "settled_idx", p.idx as i64);
            }
            return;
        }
        let Some(item) = ITEM.int(f).filter(|&v| v != 0) else { return };
        let key = (MOB_ID.int(f), item, SLOT_0D2.int(f), START.int(f));
        if let Some(&r) = self.seen.get(&key) {
            if !self.rows[r].1 {
                self.open.insert(key.2, r);
            }
            return;
        }
        let id = out.emit(
            "drops",
            Some(p),
            row! {
                item_id: item,
                quantity: QUANTITY.int(f),
                mob_id: key.0,
                mob_index: MOB_INDEX.int(f),
                slot: key.2,
                start_time: key.3,
                gold: GOLD.int(f),
                zone_id: world.zone,
            },
        );
        self.rows.push((id, false));
        self.seen.insert(key, self.rows.len() - 1);
        self.open.insert(key.2, self.rows.len() - 1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MEMBER, MOB, MapFields, drive};

    fn entry() -> (u16, MapFields) {
        let f = MapFields::new()
            .int("TrophyItemNo", 1050)
            .int("TrophyItemNum", 1)
            .int("TargetUniqueNo", MOB)
            .int("TargetActIndex", 0x010)
            .int("TrophyItemIndex", 0)
            .int("StartTime", 1_777_000_000);
        (0x0D2, f)
    }

    fn result(judge: i64, lot: i64) -> (u16, MapFields) {
        let f = MapFields::new()
            .int("TrophyItemIndex", 0)
            .int("JudgeFlg", judge)
            .int("LootUniqueNo", MEMBER)
            .text("sLootName", "Friend")
            .int("LootPoint", lot);
        (0x0D3, f)
    }

    #[test]
    fn a_coffer_key_drops() {
        let steps = vec![
            entry(),
            result(0, 412),
            entry(),
            (0x0D2, MapFields::new().int("TrophyItemNo", 0)),
            result(1, 412),
            entry(),
            result(2, 0),
        ];
        let out = drive(&mut Drops::default(), steps, Drive::default());
        let d = out.rows("drops");
        assert_eq!(d.len(), 1);
        let got: Vec<V> = ["item_id", "mob_id", "slot", "start_time"].iter().map(|c| d.get(0, c)).collect();
        assert_eq!(got, [1050, MOB, 0, 1_777_000_000].map(V::Int));
        let got: Vec<V> = ["outcome", "winner_id", "winner_name", "winning_lot"].iter().map(|c| d.get(0, c)).collect();
        assert_eq!(got, [V::Str("won".into()), V::Int(MEMBER), V::Str("Friend".into()), V::Int(412)]);
        // It left the pool at the result.
        let got: Vec<V> = ["ts_ms", "settled_ms", "settled_idx"].iter().map(|c| d.get(0, c)).collect();
        assert_eq!(got, [0, 4000, 4].map(V::Int));
    }
}
