//! world/character.py, line for line: the recording character's status (0x061), gear (0x050), and
//! /checkparam replies (0x029). Its Python twin keeps the docs.

use std::collections::HashMap;

use xc_core::combat::Resends;
use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

const JOBS: [&str; 23] = [
    "", "WAR", "MNK", "WHM", "BLM", "RDM", "THF", "PLD", "DRK", "BST", "BRD", "RNG", "SAM", "NIN", "DRG", "SMN", "BLU",
    "COR", "PUP", "DNC", "SCH", "GEO", "RUN",
];
const SLOTS: [&str; 16] = [
    "main", "sub", "range", "ammo", "head", "body", "hands", "legs", "feet", "neck", "waist", "ear1", "ear2", "ring1",
    "ring2", "back",
];
macro_rules! fields {
    ($op:expr; $($p:literal),*) => { [$(Field::new(S2C, $op, $p)),*] };
}
/// 0x061's mjob_no, mjob_lv, sjob_no, sjob_lv, hpmax, mpmax, atk, def.
static STATUS: [Field; 8] = fields!(0x061; "statusdata.mjob_no", "statusdata.mjob_lv", "statusdata.sjob_no",
    "statusdata.sjob_lv", "statusdata.hpmax", "statusdata.mpmax", "statusdata.atk", "statusdata.def");
static BASE: [Field; 7] = fields!(0x061; "statusdata.bp_base[0]", "statusdata.bp_base[1]", "statusdata.bp_base[2]",
    "statusdata.bp_base[3]", "statusdata.bp_base[4]", "statusdata.bp_base[5]", "statusdata.bp_base[6]");
static ADJ: [Field; 7] = fields!(0x061; "statusdata.bp_adj[0]", "statusdata.bp_adj[1]", "statusdata.bp_adj[2]",
    "statusdata.bp_adj[3]", "statusdata.bp_adj[4]", "statusdata.bp_adj[5]", "statusdata.bp_adj[6]");
/// 0x050's EquipKind, Category, PropertyItemIndex.
static GEAR: [Field; 3] = fields!(0x050; "EquipKind", "Category", "PropertyItemIndex");
/// 0x029's MessageNum, UniqueNoTar, Data, Data2.
static MESSAGE: [Field; 4] = fields!(0x029; "MessageNum", "UniqueNoTar", "Data", "Data2");
/// The inventory lists' Category, ItemIndex.
static ITEM_01F: [Field; 2] = fields!(0x01F; "Category", "ItemIndex");
static ITEM_020: [Field; 2] = fields!(0x020; "Category", "ItemIndex");

/// A job's abbreviation by number; None past RUN.
pub fn job(n: Option<i64>) -> Option<&'static str> {
    JOBS.get(usize::try_from(n?).ok()?).copied()
}

/// /checkparam replies, by message, as captain's checkparam addon reads them.
fn param(message: Option<i64>) -> Option<&'static str> {
    match message? {
        712 => Some("main"),
        713 => Some("sub"),
        714 => Some("ranged"),
        715 => Some("defense"),
        _ => None,
    }
}

pub static META: Meta = Meta {
    name: "character",
    version: 7,
    reads: &[(S2C, 0x061), (S2C, 0x050), (S2C, 0x01F), (S2C, 0x020), (S2C, 0x029)],
    sparse: true,
    tables: &[
        Table {
            name: "character",
            columns: &[
                ("character_id", I64),
                ("character", Str),
                ("main_job", Str),
                ("main_level", I32),
                ("sub_job", Str),
                ("sub_level", I32),
                ("hp_max", I32),
                ("mp_max", I32),
                ("str", I32),
                ("dex", I32),
                ("vit", I32),
                ("agi", I32),
                ("int", I32),
                ("mnd", I32),
                ("chr", I32),
                ("str_bonus", I32),
                ("dex_bonus", I32),
                ("vit_bonus", I32),
                ("agi_bonus", I32),
                ("int_bonus", I32),
                ("mnd_bonus", I32),
                ("chr_bonus", I32),
                ("attack", I32),
                ("defense", I32),
            ],
        },
        Table {
            name: "character_gear",
            columns: &[("character_id", I64), ("slot", Str), ("item_id", I32), ("container", I32), ("item_index", I32)],
        },
        Table {
            name: "character_params",
            columns: &[
                ("character_id", I64),
                ("kind", Str),
                ("accuracy", I32),
                ("attack", I32),
                ("evasion", I32),
                ("defense", I32),
            ],
        },
    ],
};

#[derive(Default)]
pub struct Character {
    /// (container, index) -> gear rows waiting for the inventory to name their item.
    unnamed: HashMap<(Option<i64>, Option<i64>), Vec<RowId>>,
    resends: Resends,
}

impl Extractor for Character {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        match p.opcode {
            0x061 => {
                let [mjob, mlv, sjob, slv, hp, mp, atk, def] = STATUS.each_ref().map(|x| x.int(f));
                let [str, dex, vit, agi, int, mnd, chr] = BASE.each_ref().map(|x| x.int(f));
                let [str_b, dex_b, vit_b, agi_b, int_b, mnd_b, chr_b] = ADJ.each_ref().map(|x| x.int(f));
                out.emit(
                    "character",
                    Some(p),
                    row! {
                        character_id: world.character_id, character: world.character.as_deref(),
                        main_job: job(mjob), main_level: mlv, sub_job: job(sjob), sub_level: slv,
                        hp_max: hp, mp_max: mp,
                        str: str, dex: dex, vit: vit, agi: agi, int: int, mnd: mnd, chr: chr,
                        str_bonus: str_b, dex_bonus: dex_b, vit_bonus: vit_b, agi_bonus: agi_b, int_bonus: int_b,
                        mnd_bonus: mnd_b, chr_bonus: chr_b,
                        attack: atk, defense: def,
                    },
                );
            }
            0x050 => {
                let [slot, container, index] = GEAR.each_ref().map(|x| x.int(f));
                let key = (container, index);
                let named = index.is_some_and(|i| i != 0);
                let item = if named { world.items.get(&key).copied().flatten() } else { None };
                let slot = slot.map(|s| {
                    usize::try_from(s).ok().and_then(|i| SLOTS.get(i)).map_or_else(|| s.to_string(), |s| s.to_string())
                });
                let id = out.emit(
                    "character_gear",
                    Some(p),
                    row! { character_id: world.character_id, slot: slot, item_id: item, container: container, item_index: index },
                );
                if named && item.is_none() {
                    self.unnamed.entry(key).or_default().push(id);
                }
            }
            0x029 => {
                let [num, target, a, b] = MESSAGE.each_ref().map(|x| x.int(f));
                let Some(kind) = param(num) else { return };
                let me = world.character_id.filter(|&c| c != 0);
                if me.is_none() || target != me || self.resends.is_resend(p) {
                    return;
                }
                let id = out.emit("character_params", Some(p), row! { character_id: me, kind: kind });
                let (x, y) = if kind == "defense" { ("evasion", "defense") } else { ("accuracy", "attack") };
                out.set(id, x, a);
                out.set(id, y, b);
            }
            _ => {
                let fields = if p.opcode == 0x01F { &ITEM_01F } else { &ITEM_020 };
                let [c, i] = fields.each_ref().map(|x| x.int(f));
                let key = (c, i);
                if let Some(&Some(item)) = world.items.get(&key)
                    && let Some(rows) = self.unnamed.remove(&key)
                {
                    for id in rows {
                        out.set(id, "item_id", item);
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::packets::message;
    use xc_core::testing::{Drive, MapFields, PLAYER, drive, raw};

    fn gear(slot: i64, container: i64, index: i64) -> MapFields {
        MapFields::new().int("EquipKind", slot).int("Category", container).int("PropertyItemIndex", index)
    }

    fn slot(n: i64, item: i64, container: i64, index: i64) -> MapFields {
        MapFields::new().int("ItemNum", n).int("ItemNo", item).int("Category", container).int("ItemIndex", index)
    }

    fn me(id: i64) -> Drive {
        Drive { me: id, ..Drive::default() }
    }

    #[test]
    fn gear_names_its_item_from_the_inventory() {
        let out = drive(&mut Character::default(), vec![(0x020, slot(1, 12345, 0, 7)), (0x050, gear(4, 0, 7))], me(77));
        let g = out.rows("character_gear");
        assert_eq!(
            (g.get(0, "slot"), g.get(0, "item_id"), g.get(0, "character_id")),
            ("head".into(), V::Int(12345), V::Int(77))
        );
    }

    #[test]
    fn an_update_without_a_slot_has_no_slot() {
        let f = MapFields::new().int("Category", 0).int("PropertyItemIndex", 0);
        let out = drive(&mut Character::default(), vec![(0x050, f)], me(77));
        assert_eq!(out.rows("character_gear").get(0, "slot"), V::Null);
    }

    #[test]
    fn gear_sent_before_the_inventory_gets_its_item_later() {
        let out = drive(&mut Character::default(), vec![(0x050, gear(0, 8, 3)), (0x020, slot(1, 20515, 8, 3))], me(77));
        assert_eq!(out.rows("character_gear").get(0, "item_id"), V::Int(20515));
    }

    #[test]
    fn an_emptied_slot_waits_for_its_next_item() {
        let steps = vec![
            (0x020, slot(1, 111, 8, 3)),
            (0x01E, slot(0, 0, 8, 3)),
            (0x050, gear(0, 8, 3)),
            (0x020, slot(1, 222, 8, 3)),
        ];
        let out = drive(&mut Character::default(), steps, me(77));
        assert_eq!(out.rows("character_gear").get(0, "item_id"), V::Int(222));
    }

    fn check(num: i64, target: i64, data: i64, data2: i64) -> MapFields {
        MapFields::new().int("MessageNum", num).int("UniqueNoTar", target).int("Data", data).int("Data2", data2)
    }

    #[test]
    fn a_captain_log_names_the_character_by_its_status() {
        let status = MapFields::new().int("UniqueNo", PLAYER);
        let out = drive(&mut Character::default(), vec![(0x037, status), (0x029, check(712, PLAYER, 300, 280))], me(0));
        let r = out.rows("character_params");
        assert_eq!(r.len(), 1);
        assert_eq!(
            (r.get(0, "character_id"), r.get(0, "kind"), r.get(0, "accuracy")),
            (V::Int(PLAYER), "main".into(), V::Int(300))
        );
    }

    #[test]
    fn a_resent_checkparam_gives_one_row() {
        let (_, data) = message(PLAYER, PLAYER, 712, 300, 280);
        let mut resent = data.clone();
        resent[2] = 9; // another sync counter
        let out =
            raw(Box::new(Character::default()), vec![(1000, S2C, 0x029, data), (1100, S2C, 0x029, resent)], PLAYER);
        let r = out.rows("character_params");
        assert_eq!(r.len(), 1);
        assert_eq!((r.get(0, "accuracy"), r.get(0, "attack")), (V::Int(300), V::Int(280)));
    }

    #[test]
    fn a_checkparam() {
        let steps = vec![
            (0x029, check(712, PLAYER, 1050, 1200)),
            (0x029, check(715, PLAYER, 980, 1100)),
            (0x029, check(715, PLAYER + 9, 1, 1)), // about someone else
        ];
        let out = drive(&mut Character::default(), steps, me(PLAYER));
        let r = out.rows("character_params");
        let got: Vec<_> =
            (0..r.len()).map(|i| ["kind", "accuracy", "attack", "evasion", "defense"].map(|k| r.get(i, k))).collect();
        assert_eq!(
            got,
            [
                ["main".into(), V::Int(1050), V::Int(1200), V::Null, V::Null],
                ["defense".into(), V::Null, V::Null, V::Int(980), V::Int(1100)]
            ]
        );
    }

    #[test]
    fn jobs() {
        assert_eq!(
            (job(Some(1)), job(Some(22)), job(Some(23)), job(Some(-1)), job(None)),
            (Some("WAR"), Some("RUN"), None, None, None)
        );
    }
}
