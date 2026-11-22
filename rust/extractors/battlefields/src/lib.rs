//! progress/battlefields.py, line for line: battlefield timers (0x075) with the win or loss event that ended
//! them, and the answers of registration NPCs (0x0BF). Its Python twin keeps the docs.

use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::vana::EPOCH_S;
use xc_core::{Decoded, Fields, Packet, S2C, World, row};

/// 0x075 Flags bit 0: the packet holds a countdown (LSB OBJECTIVEUTILITY_COUNTDOWN).
const COUNTDOWN: i64 = 1;
/// A countdown ending within this of the open one's end is that timer sent again.
const SAME_END_S: i64 = 5;
/// A result event this soon after the timer cleared is still its result.
const LATE_MS: i64 = 10_000;

/// LSB's battlefield events: 32001 starts on a win, 32002 on a loss.
fn outcome(event: Option<i64>) -> Option<&'static str> {
    match event? {
        32001 => Some("won"),
        32002 => Some("lost"),
        _ => None,
    }
}

/// 0x0BF Result, as LSB's instance entry sends it. 0 and 2 are unnamed.
fn registration(result: Option<i64>) -> Option<&'static str> {
    match result? {
        1 => Some("refused"),
        3 => Some("reservation failed"),
        4 => Some("entering"),
        _ => None,
    }
}

pub static META: Meta = Meta {
    name: "battlefields",
    version: 1,
    reads: &[(S2C, 0x075), (S2C, 0x0BF), (S2C, 0x032), (S2C, 0x034), (S2C, 0x00A)],
    tables: &[
        Table {
            name: "battlefields",
            columns: &[
                ("mode", I64),
                ("start_ms", I64),
                ("time_limit_s", I32),
                ("warning_s", I32),
                ("end_idx", I64),
                ("end_ms", I64),
                ("ended_by", Str),
                ("outcome", Str),
                ("result_idx", I64),
                ("battlefield_index", I32),
                ("time_inside_s", I32),
                ("record_s", I32),
                ("zone_id", I32),
            ],
        },
        Table {
            name: "registrations",
            columns: &[("result", I32), ("outcome", Str), ("npc_index", I32), ("npc_id", I64), ("zone_id", I32)],
        },
    ],
    sparse: true,
};

/// A countdown's row, and what Python reads back from it.
#[derive(Clone, Copy)]
struct Timer {
    row: RowId,
    zone: Option<i64>,
    end_ms: i64,
    outcome: bool,
}

#[derive(Default)]
pub struct Battlefields {
    open: Option<Timer>,
    /// When the open countdown runs out, server seconds.
    open_end: i64,
    /// The timer that cleared most recently, for a late result event.
    last: Option<Timer>,
}

impl Battlefields {
    fn end(&mut self, p: &Packet, why: &str, out: &mut Out) {
        if let Some(mut t) = self.open.take() {
            out.set(t.row, "end_idx", p.idx as i64);
            out.set(t.row, "end_ms", p.ts_ms);
            out.set(t.row, "ended_by", why);
            t.end_ms = p.ts_ms;
            self.last = Some(t);
        }
    }
}

impl Extractor for Battlefields {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        match p.opcode {
            0x075 => {
                if f.int("Flags").unwrap_or(0) & COUNTDOWN == 0 {
                    self.end(p, "cleared", out);
                    return;
                }
                let (start, limit) = (f.int("Timestamp").unwrap_or(0), f.int("Duration").unwrap_or(0));
                let end = start + limit;
                if self.open.is_some() && (self.open_end - end).abs() <= SAME_END_S {
                    return;
                }
                self.end(p, "replaced", out);
                let row = out.emit(
                    "battlefields",
                    Some(p),
                    row! {
                        mode: f.int("Mode"),
                        start_ms: (start + EPOCH_S) * 1000,
                        time_limit_s: limit,
                        warning_s: f.int("DurationWarn"),
                        zone_id: world.zone,
                    },
                );
                self.open = Some(Timer { row, zone: world.zone, end_ms: 0, outcome: false });
                self.open_end = end;
            }
            0x00A => {
                if self.open.is_some_and(|t| f.int("ZoneNo") != t.zone) {
                    self.end(p, "zoned", out);
                }
            }
            0x0BF => {
                let index = f.int("ActIndex");
                let result = f.int("Result");
                out.emit(
                    "registrations",
                    Some(p),
                    row! {
                        result: result,
                        outcome: registration(result),
                        npc_index: index,
                        npc_id: world.entities.get(&index).and_then(|e| e.id),
                        zone_id: world.zone,
                    },
                );
            }
            _ => {
                let Some(outcome) = outcome(f.int("EventPara")) else { return };
                let t = match (&mut self.open, &mut self.last) {
                    (Some(t), _) => t,
                    (None, Some(t)) if p.ts_ms - t.end_ms <= LATE_MS => t,
                    _ => return,
                };
                if t.outcome {
                    return;
                }
                t.outcome = true;
                out.set(t.row, "outcome", outcome);
                out.set(t.row, "result_idx", p.idx as i64);
                if outcome == "won" && p.opcode == 0x034 {
                    out.set(t.row, "record_s", f.int("num[1]"));
                    out.set(t.row, "time_inside_s", f.int("num[3]"));
                    out.set(t.row, "battlefield_index", f.int("num[5]"));
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MapFields, PLAYER, drive};

    const ZONE: i64 = 168;
    /// AOIRM1YTB1Wq's countdown Timestamp: the moment it was sent.
    const START: i64 = 783520182;

    fn countdown(limit: i64, start: i64) -> (u16, MapFields) {
        let f = MapFields::new()
            .int("Mode", 1)
            .int("Timestamp", start)
            .int("Duration", limit)
            .int("DurationWarn", 0)
            .int("Flags", 1);
        (0x075, f)
    }

    /// Retail clears with Flags 0 and leaves the rest as it was: garbage.
    fn clear() -> (u16, MapFields) {
        (
            0x075,
            MapFields::new().int("Mode", 1).int("Timestamp", 3087468518).int("Duration", 3286727262).int("Flags", 0),
        )
    }

    fn zone_in(zone: i64) -> (u16, MapFields) {
        (0x00A, MapFields::new().int("ZoneNo", zone))
    }

    fn rows(steps: Vec<(u16, MapFields)>, table: &str, cols: &[&str]) -> Vec<Vec<V>> {
        let out = drive(&mut Battlefields::default(), steps, Drive::default());
        let r = out.rows(table);
        (0..r.len()).map(|i| cols.iter().map(|c| r.get(i, c)).collect()).collect()
    }

    fn s(x: &str) -> V {
        V::Str(x.into())
    }

    #[test]
    fn a_battlefield_won_its_time_limit_and_index() {
        let mut won = MapFields::new().int("UniqueNo", PLAYER).int("EventPara", 32001);
        for (i, n) in [0, 28, 0, 442, ZONE, 2, 0, 0].into_iter().enumerate() {
            won = won.int(&format!("num[{i}]"), n);
        }
        let steps =
            vec![zone_in(ZONE), countdown(1800, START), countdown(1799, START + 1), (0x034, won), clear(), clear()];
        let cols = [
            "start_ms",
            "time_limit_s",
            "mode",
            "zone_id",
            "outcome",
            "result_idx",
            "battlefield_index",
            "time_inside_s",
            "record_s",
            "end_idx",
            "ended_by",
        ];
        let want = [(START + EPOCH_S) * 1000, 1800, 1, ZONE].map(V::Int).into_iter();
        let want = want.chain([s("won")]).chain([3, 2, 442, 28, 4].map(V::Int)).chain([s("cleared")]);
        assert_eq!(rows(steps, "battlefields", &cols), [want.collect::<Vec<_>>()]);
    }

    #[test]
    fn a_loss_after_the_clear_and_a_timer_that_never_cleared() {
        let loss = (0x032, MapFields::new().int("EventPara", 32002));
        let steps =
            vec![zone_in(ZONE), countdown(1800, START), clear(), loss, countdown(900, START + 5000), zone_in(ZONE + 1)];
        assert_eq!(
            rows(steps, "battlefields", &["time_limit_s", "outcome", "ended_by"]),
            [vec![V::Int(1800), s("lost"), s("cleared")], vec![V::Int(900), V::Null, s("zoned")],]
        );
    }

    #[test]
    fn a_new_countdown_replaces_the_open_one() {
        let steps = vec![zone_in(ZONE), countdown(360, START), countdown(360, START + 400)];
        assert_eq!(
            rows(steps, "battlefields", &["time_limit_s", "ended_by"]),
            [vec![V::Int(360), s("replaced")], vec![V::Int(360), V::Null],]
        );
    }

    #[test]
    fn a_registration_answer_names_its_npc() {
        let npc = 0x01000000 | (137 << 12) | 0x297;
        let steps = vec![
            (0x00E, MapFields::new().int("UniqueNo", npc).int("ActIndex", 0x297)),
            (0x0BF, MapFields::new().int("Result", 4).int("ActIndex", 0x297)),
            (0x0BF, MapFields::new().int("Result", 2).int("ActIndex", 0x300)),
        ];
        assert_eq!(
            rows(steps, "registrations", &["result", "outcome", "npc_id"]),
            [vec![V::Int(4), s("entering"), V::Int(npc)], vec![V::Int(2), V::Null, V::Null],]
        );
    }
}
