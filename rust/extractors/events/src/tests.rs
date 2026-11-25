//! tests/progress/test_events.py's events cases, on the same bytes.

use super::*;
use xc_core::V;
use xc_core::testing::raw;
use xc_link::packets::*;

fn run(packets: Vec<(i64, Raw)>) -> Out {
    raw(Box::new(Events::default()), timed(packets), PLAYER)
}

fn col(out: &Out, table: &str, name: &str) -> Vec<V> {
    let r = out.rows(table);
    (0..r.len()).map(|i| r.get(i, name)).collect()
}

fn s(x: &str) -> V {
    V::Str(x.into())
}

fn ints(xs: &[i64]) -> V {
    V::Ints(xs.iter().map(|&x| Some(x)).collect())
}

#[test]
fn a_home_point() {
    let out = run(vec![
        (1000, event_num(8700, [1, 2, 3, 4, 5, 6, 7, 8])),
        (2000, reply(8700, 2, 1)),
        (2100, update([9, 0, 0, 0, 0, 0, 0, 0])),
        (3000, reply(8700, 0x10002, 0)),
        (3100, release()),
    ]);
    assert_eq!(col(&out, "events", "kind"), ["start", "reply", "update", "reply", "release"].map(s));
    assert!(col(&out, "events", "event_idx").iter().all(|v| *v == V::Int(0)));
    let r = out.rows("events");
    let start = ["npc_id", "npc_index", "event_id", "mode"].map(|c| r.get(0, c));
    assert_eq!(start, [NPC as i64, 100, 8700, 8].map(V::Int));
    assert_eq!(r.get(0, "params"), ints(&[1, 2, 3, 4, 5, 6, 7, 8]));
    assert_eq!(r.get(2, "params"), ints(&[9, 0, 0, 0, 0, 0, 0, 0]));
    assert_eq!((r.get(1, "mode"), r.get(1, "option")), (V::Int(1), V::Int(2)));
    assert_eq!((r.get(3, "mode"), r.get(3, "option")), (V::Int(0), V::Int(0x10002)));
}

#[test]
fn a_quest_completed() {
    let out = run(vec![
        (0, log(0x98, [0; 8])),
        (1000, event_num(10, [0; 8])),
        (2000, reply(10, 0, 0)),
        (2100, release()),
        (2200, log(0x98, [0, 1 << 5, 0, 0, 0, 0, 0, 0])),
        (90_000, log(0x98, [0, 1 << 5 | 1, 0, 0, 0, 0, 0, 0])),
    ]);
    let r = out.rows("log_changes");
    assert_eq!(r.len(), 2);
    assert_eq!(
        ["log", "area", "id", "action"].map(|c| r.get(0, c)),
        [s("quests_done"), s("Bastok"), V::Int(37), s("completed")]
    );
    assert_eq!((r.get(0, "event_idx"), r.get(0, "event_id")), (V::Int(1), V::Int(10)));
    assert_eq!((r.get(1, "id"), r.get(1, "event_idx")), (V::Int(32), V::Null), "long after the event");
}

#[test]
fn main_mission_progress() {
    let out = run(vec![(0, log(0xFFFF, [1, 5, 0, 0, 0, 0, 0, 0])), (1, log(0xFFFF, [1, 6, 0, 0, 0, 0, 0, 0]))]);
    let r = out.rows("log_changes");
    assert_eq!(r.len(), 1);
    assert_eq!(
        ["log", "area", "old", "new", "id"].map(|c| r.get(0, c)),
        [s("main"), s("Nation mission"), V::Int(5), V::Int(6), V::Null]
    );
}

#[test]
fn a_reward_after_a_warp_follows_its_event() {
    let after = |n: u32| log(0x98, [(1 << n) - 1, 0, 0, 0, 0, 0, 0, 0]);
    let out = run(vec![
        (0, log(0x98, [0; 8])),
        (1000, event_num(8700, [0; 8])),
        (2000, release()),
        (3000, zone_in()),
        (5000, after(1)),
        (6000, event_num(8800, [0; 8])),
        (7000, after(2)),
    ]);
    assert_eq!(col(&out, "log_changes", "event_id"), [V::Int(8700), V::Int(8800)]);
}

#[test]
fn a_log_change_after_the_zone_in_lists_follows_no_event_before_it() {
    let out = run(vec![
        (0, log(0x98, [0; 8])),
        (1000, event_num(8500, [0; 8])),
        (2000, zone_in()),
        (3000, log(0x98, [0; 8])),
        (16_000, release()),
        (17_000, log(0x98, [1, 0, 0, 0, 0, 0, 0, 0])),
    ]);
    assert_eq!(col(&out, "log_changes", "event_id"), [V::Null]);
}

#[test]
fn an_update_with_strings() {
    let out = run(vec![
        (1000, event_num(8700, [0; 8])),
        (2000, reply(8700, 3, 1)),
        (2100, update_strings([5, 0, 0, 0, 0, 0, 0, 0, 9], ["Nours", "", "Sword", ""])),
    ]);
    let r = out.rows("events");
    assert_eq!(["kind", "opcode", "event_idx"].map(|c| r.get(2, c)), [s("update"), V::Int(0x05D), V::Int(0)]);
    assert_eq!(r.get(2, "params"), ints(&[5, 0, 0, 0, 0, 0, 0, 0, 9]));
    assert_eq!(r.get(2, "strings"), V::Strs(vec![Some("Nours".into()), None, Some("Sword".into()), None]));
}

#[test]
fn log_bits_by_port() {
    let mut got = Vec::new();
    log_changes(Some(0xD8), &[0; 8], &[0, 0, 0b10, 0, 0, 0, 0, 0], |c| got.push(c));
    log_changes(Some(0x80), &[0; 8], &[1, 0, 0, 0, 9, 0, 0, 0], |c| got.push(c));
    log_changes(None, &[0; 8], &[0, 1, 0, 0, 0, 0, 0, 0], |c| got.push(c));
    assert_eq!(
        got,
        [
            ("missions_done", Some("WotG"), 2, 0, 2, Some(1), "completed"),
            ("quests_current", Some("Aht Urhgan"), 0, 0, 1, Some(0), "accepted"),
            ("progress", Some("Assault"), 4, 0, 9, None, "set"),
            ("unknown", None, 1, 0, 1, None, "set"),
        ]
    );
}
