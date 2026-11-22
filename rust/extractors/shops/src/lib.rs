//! items/shops.py, line for line: NPC and guild shops' lists, openings, and purchases, with the character's
//! nation and rank. Its Python twin keeps the docs.

use std::collections::HashMap;
use std::sync::LazyLock;

use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::{C2S, Decoded, Field, Packet, S2C, V, World, row};

/// 0x061's nation, and the order of 0x05E's balance.
const NATIONS: [&str; 3] = ["San d'Oria", "Bastok", "Windurst"];

fn field(dir: u8, op: u16, path: String) -> Field {
    Field::new(dir, op, path.leak())
}

static TALK: [Field; 2] = [Field::new(C2S, 0x01A, "ActionID"), Field::new(C2S, 0x01A, "UniqueNo")];
static NPC_032: Field = Field::new(S2C, 0x032, "UniqueNo");
static NPC_034: Field = Field::new(S2C, 0x034, "UniqueNo");
static STATUS: [Field; 2] = [Field::new(S2C, 0x061, "statusdata.nation"), Field::new(S2C, 0x061, "statusdata.rank")];
static BALANCE: Field = Field::new(S2C, 0x05E, "Conquest.Balance");
static OPENED: Field = Field::new(S2C, 0x03E, "ShopListNum");
static GUILD_STATE: [Field; 2] = [Field::new(S2C, 0x086, "Stat"), Field::new(S2C, 0x086, "Time")];
static BUY: [Field; 2] = [Field::new(C2S, 0x083, "ShopItemIndex"), Field::new(C2S, 0x083, "ItemNum")];
static BOUGHT: [Field; 2] = [Field::new(S2C, 0x03F, "Count"), Field::new(S2C, 0x03F, "BuyState")];
static GUILD_BUY: [Field; 2] = [Field::new(C2S, 0x0AA, "ItemNo"), Field::new(C2S, 0x0AA, "ItemNum")];
static GUILD_BOUGHT: [Field; 3] =
    [Field::new(S2C, 0x082, "ItemNo"), Field::new(S2C, 0x082, "Trade"), Field::new(S2C, 0x082, "Count")];
/// Each NPC shop list entry's ItemNo, ItemPrice, ShopIndex, Skill, GuildInfo: up to 19 a packet, as LSB sends.
static SHOP: LazyLock<Vec<[Field; 5]>> = LazyLock::new(|| {
    (0..19)
        .map(|i| {
            ["ItemNo", "ItemPrice", "ShopIndex", "Skill", "GuildInfo"]
                .map(|k| field(S2C, 0x03C, format!("ShopItemTbl[{i}].{k}")))
        })
        .collect()
});
/// A guild list's Stat and Count, then each entry's ItemNo, Price, Count, Max: 0x083's, then 0x085's.
type GuildFields = ([Field; 2], Vec<[Field; 4]>);
static GUILD: LazyLock<[GuildFields; 2]> = LazyLock::new(|| {
    [0x083, 0x085].map(|op| {
        let list =
            (0..30).map(|i| ["ItemNo", "Price", "Count", "Max"].map(|k| field(S2C, op, format!("List[{i}].{k}"))));
        ([Field::new(S2C, op, "Stat"), Field::new(S2C, op, "Count")], list.collect())
    })
});

/// A guild's opening hours from 0x086, as LSB packs them: bits open to close - 1 of Time set. Retail sends
/// them only while the guild is closed (Stat 1).
pub fn hours(stat: Option<i64>, time: Option<i64>) -> (Option<i64>, Option<i64>) {
    let Some(time) = time.filter(|&t| stat == Some(1) && t != 0) else { return (None, None) };
    let set = |h: i64| time >> h & 1 != 0;
    let Some(first) = (0..24).find(|&h| set(h)) else { return (None, None) };
    let last = (0..24).rev().find(|&h| set(h)).unwrap();
    if (first..=last).all(set) { (Some(first), Some(last + 1)) } else { (None, None) }
}

pub static META: Meta = Meta {
    name: "shops",
    version: 1,
    reads: &[
        (C2S, 0x01A),
        (S2C, 0x032),
        (S2C, 0x034),
        (S2C, 0x061),
        (S2C, 0x05E),
        (S2C, 0x03E),
        (S2C, 0x03C),
        (C2S, 0x083),
        (S2C, 0x03F),
        (S2C, 0x086),
        (S2C, 0x083),
        (S2C, 0x085),
        (C2S, 0x0AA),
        (S2C, 0x082),
    ],
    sparse: true,
    tables: &[
        Table {
            name: "shop_items",
            columns: &[
                ("kind", Str),
                ("npc_id", I64),
                ("list_idx", I64),
                ("item_id", I32),
                ("price", I64),
                ("shop_index", I32),
                ("stock", I32),
                ("max", I32),
                ("skill", I32),
                ("guild_info", I32),
                ("nation", Str),
                ("nation_rank", I32),
                ("conquest_rank", I32),
                ("zone_id", I32),
            ],
        },
        Table {
            name: "shop_actions",
            columns: &[
                ("action", Str),
                ("npc_id", I64),
                ("items", I32),
                ("item_id", I32),
                ("quantity", I64),
                ("price", I64),
                ("bought", I64),
                ("buy_state", I32),
                ("stock", I32),
                ("guild_status", I32),
                ("guild_time", I64),
                ("open_hour", I32),
                ("close_hour", I32),
                ("zone_id", I32),
            ],
        },
    ],
};

/// A guild list as last opened: its first packet's idx, and its prices by item.
struct GuildList {
    idx: u64,
    prices: HashMap<i64, Option<i64>>,
}

/// A purchase the server has yet to answer: its row, whether from a guild, and the item asked for.
struct Buy {
    row: RowId,
    guild: bool,
    item: Option<i64>,
}

#[derive(Default)]
pub struct Shops {
    npc: Option<i64>,
    nation: Option<i64>,
    rank: Option<i64>,
    balance: Option<i64>,
    /// An NPC shop's list: shop index -> (item, price).
    list: HashMap<Option<i64>, (i64, Option<i64>)>,
    list_idx: Option<u64>,
    /// Guild list opcode -> the list.
    guild: HashMap<u16, GuildList>,
    buy: Option<Buy>,
}

impl Extractor for Shops {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        match p.key() {
            (C2S, 0x01A) => {
                // A talk.
                if !TALK[0].flag(f) {
                    self.npc = TALK[1].int(f);
                }
            }
            (S2C, 0x032) => self.npc = NPC_032.int(f),
            (S2C, 0x034) => self.npc = NPC_034.int(f),
            (S2C, 0x061) => [self.nation, self.rank] = STATUS.each_ref().map(|x| x.int(f)),
            (S2C, 0x05E) => self.balance = BALANCE.int(f),
            (S2C, 0x03E) => {
                (self.list, self.list_idx) = (HashMap::new(), Some(p.idx));
                self.act(out, p, world, "open", row! { items: OPENED.int(f) });
            }
            (S2C, 0x03C) => self.shop_list(p, f, world, out),
            (S2C, 0x083 | 0x085) => self.guild_list(p, f, world, out),
            (S2C, 0x086) => {
                let [stat, time] = GUILD_STATE.each_ref().map(|x| x.int(f));
                let (open, close) = hours(stat, time);
                let values = row! { guild_status: stat, guild_time: time, open_hour: open, close_hour: close };
                self.act(out, p, world, "guild", values);
            }
            (C2S, 0x083) => {
                let (item, price) = self.list.get(&BUY[0].int(f)).map_or((None, None), |&(i, p)| (Some(i), p));
                let row = self.act(out, p, world, "buy", row! { item_id: item, quantity: BUY[1].int(f), price: price });
                self.buy = Some(Buy { row, guild: false, item });
            }
            (S2C, 0x03F) => {
                if let Some(b) = self.buy.take()
                    && !b.guild
                {
                    out.set(b.row, "bought", BOUGHT[0].int(f));
                    out.set(b.row, "buy_state", BOUGHT[1].int(f));
                }
            }
            (C2S, 0x0AA) => {
                let item = GUILD_BUY[0].int(f);
                let price = item.and_then(|i| self.guild.get(&0x083)?.prices.get(&i).copied().flatten());
                let row = self.act(
                    out,
                    p,
                    world,
                    "guild_buy",
                    row! { item_id: item, quantity: GUILD_BUY[1].int(f), price: price },
                );
                self.buy = Some(Buy { row, guild: true, item });
            }
            (S2C, 0x082) => {
                if let Some(b) = self.buy.take()
                    && b.guild
                    && GUILD_BOUGHT[0].int(f) == b.item
                {
                    out.set(b.row, "bought", GUILD_BOUGHT[1].int(f));
                    out.set(b.row, "stock", GUILD_BOUGHT[2].int(f));
                }
            }
            _ => {}
        }
    }
}

impl Shops {
    fn act<const N: usize>(
        &self,
        out: &mut Out,
        p: &Packet,
        world: &World,
        action: &str,
        values: [(&str, V); N],
    ) -> RowId {
        let id = out.emit("shop_actions", Some(p), values);
        for (k, v) in row! { action: action, npc_id: self.npc, zone_id: world.zone } {
            out.set(id, k, v);
        }
        id
    }

    /// The character's nation, its rank, and the nation's conquest standing.
    fn standing(&self) -> (Option<&'static str>, Option<i64>, Option<i64>) {
        let n = self.nation.and_then(|n| usize::try_from(n).ok()).filter(|&n| n < 3);
        let rank = n.and_then(|n| Some(self.balance? >> (2 * n) & 3));
        (n.map(|n| NATIONS[n]), self.rank, rank)
    }

    fn shop_list(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let list_idx = *self.list_idx.get_or_insert(p.idx) as i64;
        let (nation, nation_rank, conquest_rank) = self.standing();
        for t in SHOP.iter() {
            let Some(item) = t[0].int(f).filter(|&i| i != 0) else { continue };
            let (price, index) = (t[1].int(f), t[2].int(f));
            self.list.insert(index, (item, price));
            out.emit(
                "shop_items",
                Some(p),
                row! {
                    kind: "shop", list_idx: list_idx, item_id: item, price: price, shop_index: index,
                    skill: t[3].int(f), guild_info: t[4].int(f), zone_id: world.zone,
                    nation: nation, nation_rank: nation_rank, conquest_rank: conquest_rank, npc_id: self.npc,
                },
            );
        }
    }

    fn guild_list(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let ([stat, count], list) = &GUILD[usize::from(p.opcode == 0x085)];
        let stat = stat.int(f).unwrap_or(0);
        // A list's first packet: 0x40 of several, 0x80 of one.
        if stat & 0x3F == 0 || !self.guild.contains_key(&p.opcode) {
            self.guild.insert(p.opcode, GuildList { idx: p.idx, prices: HashMap::new() });
        }
        let (nation, nation_rank, conquest_rank) = self.standing();
        let kind = if p.opcode == 0x083 { "guild_sells" } else { "guild_buys" };
        let (npc, g) = (self.npc, self.guild.get_mut(&p.opcode).unwrap());
        let count = count.int(f).unwrap_or(0).clamp(0, 30) as usize;
        for t in &list[..count] {
            let Some(item) = t[0].int(f).filter(|&i| i != 0) else { continue };
            let price = t[1].int(f);
            g.prices.insert(item, price);
            out.emit(
                "shop_items",
                Some(p),
                row! {
                    kind: kind, list_idx: g.idx as i64, item_id: item, price: price, stock: t[2].int(f),
                    max: t[3].int(f), zone_id: world.zone,
                    nation: nation, nation_rank: nation_rank, conquest_rank: conquest_rank, npc_id: npc,
                },
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::testing::{Drive, MapFields, drive};

    const ZONE: i64 = 235; // Bastok Markets
    const NPC: i64 = 0x0100_0000 | (ZONE << 12) | 0x10C;
    const GUILD_NPC: i64 = NPC + 1;
    const STEW: i64 = 4569;
    const ORE: i64 = 644;
    const INGOT: i64 = 790;

    fn talk(npc: i64) -> (u16, MapFields) {
        (0x01A, MapFields::new().int("UniqueNo", npc).int("ActIndex", npc & 0xFFF).int("ActionID", 0))
    }

    fn shop_list(items: &[(i64, i64, i64)]) -> (u16, MapFields) {
        let mut d = MapFields::new().int("ShopItemOffsetIndex", 0);
        for (i, &(index, item, price)) in items.iter().enumerate() {
            let t = format!("ShopItemTbl[{i}].");
            d = d
                .int(&format!("{t}ItemNo"), item)
                .int(&format!("{t}ItemPrice"), price)
                .int(&format!("{t}ShopIndex"), index)
                .int(&format!("{t}Skill"), 0);
        }
        (0x03C, d)
    }

    fn guild_list(stat: i64, items: &[(i64, i64, i64, i64)]) -> (u16, MapFields) {
        let mut d = MapFields::new().int("Stat", stat).int("Count", items.len() as i64);
        for (i, &(item, count, most, price)) in items.iter().enumerate() {
            d = d
                .int(&format!("List[{i}].ItemNo"), item)
                .int(&format!("List[{i}].Count"), count)
                .int(&format!("List[{i}].Max"), most)
                .int(&format!("List[{i}].Price"), price);
        }
        (0x083, d)
    }

    fn f(pairs: &[(&str, i64)]) -> MapFields {
        pairs.iter().fold(MapFields::new(), |d, &(k, v)| d.int(k, v))
    }

    #[test]
    fn guild_hours_come_only_with_a_closed_guild() {
        assert_eq!(hours(Some(1), Some(0x807FFF00)), (Some(8), Some(23))); // Bastok's smiths, the client not told
        assert_eq!(hours(Some(1), Some(0x000FFFE0)), (Some(5), Some(20)));
        assert_eq!(hours(Some(0), Some(261379)), (None, None)); // open: Time is whatever the buffer held
        assert_eq!(hours(Some(1), Some(0b1011 << 8)), (None, None)); // no run of hours
    }

    #[test]
    fn a_shop_and_a_guild_with_the_characters_standing_and_purchases() {
        let steps = vec![
            (0x00A, f(&[("ZoneNo", ZONE)])),
            (0x061, f(&[("statusdata.nation", 1), ("statusdata.rank", 8)])), // Bastok, rank 8
            (0x05E, f(&[("Conquest.Balance", 0b11_10_01)])),                 // San d'Oria 1st, Bastok 2nd
            talk(NPC),
            (0x03E, f(&[("ShopListNum", 2)])),
            shop_list(&[(0, STEW, 60), (1, ORE, 200)]),
            (0x083, f(&[("ShopItemIndex", 1), ("ItemNum", 12)])), // the character buys 12 ore
            (0x03F, f(&[("ShopItemIndex", 1), ("BuyState", 1), ("Count", 12)])),
            talk(GUILD_NPC),
            (0x086, f(&[("Stat", 1), ("Time", 0x007FFF00)])),
            guild_list(0x40, &[(INGOT, 30, 80, 8000)]), // a list in two packets
            guild_list(0x81, &[(ORE, 5, 40, 210)]),
            (0x0AA, f(&[("ItemNo", INGOT), ("ItemNum", 10)])),
            (0x082, f(&[("ItemNo", INGOT), ("Count", 20), ("Trade", 10)])),
        ];
        let directions = [0, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0].to_vec();
        let out = drive(&mut Shops::default(), steps, Drive { directions: Some(directions), ..Drive::default() });
        let n = |v: Option<i64>| V::from(v);
        let s = |v: &str| V::from(v);
        let items = out.rows("shop_items");
        let keys = [
            "kind",
            "npc_id",
            "list_idx",
            "item_id",
            "price",
            "stock",
            "max",
            "nation",
            "nation_rank",
            "conquest_rank",
        ];
        let got: Vec<_> = (0..items.len()).map(|i| keys.map(|k| items.get(i, k))).collect();
        let item = |kind, npc, idx, id, price, stock: Option<i64>, max: Option<i64>| {
            [
                s(kind),
                n(Some(npc)),
                n(Some(idx)),
                n(Some(id)),
                n(Some(price)),
                n(stock),
                n(max),
                s("Bastok"),
                n(Some(8)),
                n(Some(2)),
            ]
        };
        assert_eq!(
            got,
            [
                item("shop", NPC, 4, STEW, 60, None, None),
                item("shop", NPC, 4, ORE, 200, None, None),
                item("guild_sells", GUILD_NPC, 10, INGOT, 8000, Some(30), Some(80)),
                item("guild_sells", GUILD_NPC, 10, ORE, 210, Some(5), Some(40)),
            ]
        );
        let acts = out.rows("shop_actions");
        let keys =
            ["action", "npc_id", "items", "item_id", "quantity", "price", "bought", "stock", "open_hour", "close_hour"];
        let got: Vec<_> = (0..acts.len()).map(|i| keys.map(|k| acts.get(i, k))).collect();
        let none = None;
        assert_eq!(
            got,
            [
                [s("open"), n(Some(NPC)), n(Some(2)), n(none), n(none), n(none), n(none), n(none), n(none), n(none)],
                [
                    s("buy"),
                    n(Some(NPC)),
                    n(none),
                    n(Some(ORE)),
                    n(Some(12)),
                    n(Some(200)),
                    n(Some(12)),
                    n(none),
                    n(none),
                    n(none)
                ],
                [
                    s("guild"),
                    n(Some(GUILD_NPC)),
                    n(none),
                    n(none),
                    n(none),
                    n(none),
                    n(none),
                    n(none),
                    n(Some(8)),
                    n(Some(23))
                ],
                [
                    s("guild_buy"),
                    n(Some(GUILD_NPC)),
                    n(none),
                    n(Some(INGOT)),
                    n(Some(10)),
                    n(Some(8000)),
                    n(Some(10)),
                    n(Some(20)),
                    n(none),
                    n(none)
                ],
            ]
        );
    }
}
