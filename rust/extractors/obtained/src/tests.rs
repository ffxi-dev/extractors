//! tests/items/test_loot.py's obtained cases.

use super::*;
use xc_core::V;
use xc_core::testing::{Drive, MOB, MapFields, PLAYER, drive};

const INV: i64 = 0;
const SATCHEL: i64 = 5;
const BIN: i64 = 17;

fn put(c: i64, i: i64, item: i64, n: i64) -> (u16, MapFields) {
    (0x020, MapFields::new().int("Category", c).int("ItemIndex", i).int("ItemNo", item).int("ItemNum", n))
}

fn synced(flags: i64) -> (u16, MapFields) {
    (0x01D, MapFields::new().int("Flags", flags))
}

/// (idx, item, quantity, source, event_idx) of each row. After a zone-in the server sends the inventory and
/// the satchel whole.
fn obtained(timed: Vec<(i64, (u16, MapFields))>) -> Vec<(V, V, V, V, V)> {
    let held = || vec![put(INV, 0, 0xFFFF, 1000), put(INV, 1, 4098, 5)]; // gil, 5 wind crystals
    let mut steps = held();
    steps.push((0x00A, MapFields::new().int("ZoneNo", 0x0A3)));
    steps.extend(held());
    steps.extend([synced(1), put(SATCHEL, 1, 1050, 1), synced(1 | 1 << SATCHEL)]);
    let mut times = vec![0; steps.len()];
    for (t, s) in timed {
        times.push(t);
        steps.push(s);
    }
    let out = drive(&mut Obtained::default(), steps, Drive { times: Some(times), ..Drive::default() });
    let r = out.rows("obtained");
    let c = |i, k| r.get(i, k);
    (0..r.len()).map(|i| (c(i, "idx"), c(i, "item_id"), c(i, "quantity"), c(i, "source"), c(i, "event_idx"))).collect()
}

fn got(idx: i64, item: i64, n: i64, pool: bool, event: Option<i64>) -> (V, V, V, V, V) {
    (V::Int(idx), V::Int(item), V::Int(n), pool.then_some("pool").into(), event.into())
}

#[test]
fn what_the_character_held_is_not_obtained() {
    assert_eq!(obtained(vec![]), []);
}

#[test]
fn an_item_into_an_empty_slot_or_a_bigger_stack() {
    let more = (0x01E, MapFields::new().int("Category", INV).int("ItemIndex", 1).int("ItemNum", 8));
    let rows = obtained(vec![(5000, put(INV, 2, 2861, 1)), (9000, more)]);
    assert_eq!(rows, [got(8, 2861, 1, false, None), got(9, 4098, 3, false, None)]);
}

#[test]
fn a_move_a_sort_gil_or_a_drop_is_not_obtained() {
    let rows = obtained(vec![
        (5000, put(INV, 1, 0, 0)),
        (5000, put(SATCHEL, 2, 4098, 5)), // to the satchel
        (9000, put(SATCHEL, 1, 0, 0)),
        (9300, put(INV, 7, 1050, 1)),       // back, a tick later
        (12000, put(INV, 0, 0xFFFF, 5000)), // gil
        (15000, put(INV, 7, 0, 0)),
        (15000, put(BIN, 1, 1050, 1)), // dropped
    ]);
    assert_eq!(rows, []);
}

#[test]
fn a_reward_after_a_zone_in_cutscene_follows_it() {
    let zone_in = MapFields::new().int("ZoneNo", 0x0A3).int("EventNum", 1).int("EventPara", 100);
    let rows =
        obtained(vec![(5000, (0x00A, zone_in)), (5000, synced(1 | 1 << SATCHEL)), (6000, put(INV, 2, 13014, 1))]);
    assert_eq!(rows, [got(10, 13014, 1, false, Some(8))]);
}

#[test]
fn an_item_taken_back_out_of_the_recycle_bin_is_not_obtained() {
    let rows = obtained(vec![
        (5000, put(INV, 1, 0, 0)),
        (5000, put(BIN, 1, 4098, 5)), // dropped
        (9000, put(BIN, 1, 0, 0)),
        (9000, put(INV, 1, 4098, 5)), // taken back
    ]);
    assert_eq!(rows, []);
}

#[test]
fn a_pool_win_and_a_quest_reward() {
    let entry = MapFields::new()
        .int("TrophyItemNo", 1050)
        .int("TrophyItemNum", 1)
        .int("TargetUniqueNo", MOB)
        .int("TargetActIndex", 0x010)
        .int("TrophyItemIndex", 0)
        .int("StartTime", 1_777_000_000);
    let win = MapFields::new().int("TrophyItemIndex", 0).int("JudgeFlg", 1).int("LootUniqueNo", PLAYER);
    let rows = obtained(vec![
        (5000, (0x0D2, entry)),
        (6000, (0x0D3, win)),
        (6000, put(INV, 2, 1050, 1)),
        (20000, (0x032, MapFields::new())),
        (25000, put(INV, 3, 13014, 1)),
    ]);
    assert_eq!(rows, [got(10, 1050, 1, true, None), got(12, 13014, 1, false, Some(11))]);
}
