//! progress/events.py, line for line: every event packet with its parameters and the replies, NPC messages,
//! and mission and quest log changes (0x056), each linked to the event under way. Its Python twin keeps the
//! docs.

use std::collections::HashMap;

use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{C2S, Decoded, Fields, Packet, S2C, World, row};
use xc_link::{Kind, Link, Resent, Start, kind};

/// Mission and quest log ports (0x056), as missiontrack reads them.
fn current(port: i64) -> Option<&'static str> {
    Some(match port {
        0x50 => "San d'Oria",
        0x58 => "Bastok",
        0x60 => "Windurst",
        0x68 => "Jeuno",
        0x70 => "Other Areas",
        0x78 => "Outlands",
        0x80 => "Aht Urhgan",
        0x88 => "Crystal War",
        0xE0 => "Abyssea",
        0xF0 => "Adoulin",
        0x100 => "Coalition",
        _ => return None,
    })
}

fn done(port: i64) -> Option<&'static str> {
    Some(match port {
        0x90 => "San d'Oria",
        0x98 => "Bastok",
        0xA0 => "Windurst",
        0xA8 => "Jeuno",
        0xB0 => "Other Areas",
        0xB8 => "Outlands",
        0xC0 => "Aht Urhgan",
        0xC8 => "Crystal War",
        0xE8 => "Abyssea",
        0xF8 => "Adoulin",
        0x108 => "Coalition",
        _ => return None,
    })
}

fn missions(port: i64) -> Option<&'static str> {
    Some(match port {
        0x30 => "Campaign (1-256)",
        0x38 => "Campaign (257-512)",
        0xD0 => "Nations and RotZ",
        0xD8 => "ToAU and WotG",
        _ => return None,
    })
}

const MAIN: [&str; 8] = ["Nation", "Nation mission", "RotZ", "CoP", "CoP extended", "Addons and tales", "SoA", "RoV"];

/// Port 0x80's last four.
fn progress(i: usize) -> Option<&'static str> {
    Some(match i {
        4 => "Assault",
        5 => "ToAU mission",
        6 => "WotG mission",
        7 => "Campaign",
        _ => return None,
    })
}

/// One log change: (log, area, field, old, new, id, action).
pub type Change = (&'static str, Option<&'static str>, usize, i64, i64, Option<i64>, &'static str);

/// missiontrack's reading of one 0x056 change, a call per change.
pub fn log_changes(port: Option<i64>, old: &[i64; 8], new: &[i64; 8], mut emit: impl FnMut(Change)) {
    for (i, (&a, &b)) in old.iter().zip(new).enumerate() {
        if a == b {
            continue;
        }
        let Some(port) = port else {
            emit(("unknown", None, i, a, b, None, "set"));
            continue;
        };
        if port == 0xFFFF {
            emit(("main", Some(MAIN[i]), i, a, b, None, "set"));
        } else if let Some(area) = progress(i).filter(|_| port == 0x80) {
            emit(("progress", Some(area), i, a, b, None, "set"));
        } else if current(port).is_some() || done(port).is_some() || missions(port).is_some() {
            for bit in 0..32 {
                if (a ^ b) >> bit & 1 == 0 {
                    continue;
                }
                let now = b >> bit & 1 != 0;
                let id = (i * 32 + bit) as i64;
                if let Some(area) = current(port) {
                    emit(("quests_current", Some(area), i, a, b, Some(id), if now { "accepted" } else { "removed" }));
                } else if port == 0xD8 {
                    let (area, n) = if i < 2 { ("ToAU", i) } else { ("WotG", i - 2) };
                    let id = (n * 32 + bit) as i64;
                    emit(("missions_done", Some(area), i, a, b, Some(id), if now { "completed" } else { "reset" }));
                } else {
                    let log = if done(port).is_some() { "quests_done" } else { "missions_done" };
                    let area = done(port).or_else(|| missions(port));
                    emit((log, area, i, a, b, Some(id), if now { "completed" } else { "reset" }));
                }
            }
        } else {
            emit((if port == 0xFFFE { "tvr" } else { "unknown" }, None, i, a, b, None, "set"));
        }
    }
}

pub static META: Meta = Meta {
    name: "events",
    version: 3,
    reads: &[
        (S2C, 0x032),
        (S2C, 0x033),
        (S2C, 0x034),
        (S2C, 0x05C),
        (S2C, 0x05D),
        (C2S, 0x05B),
        (C2S, 0x05C),
        (S2C, 0x052),
        (S2C, 0x036),
        (S2C, 0x027),
        (S2C, 0x02A),
        (S2C, 0x053),
        (S2C, 0x00A),
        (S2C, 0x056),
    ],
    tables: &[
        Table {
            name: "events",
            columns: &[
                ("kind", Str),
                ("opcode", I32),
                ("event_idx", I64),
                ("npc_id", I64),
                ("npc_index", I32),
                ("event_id", I32),
                ("event_num", I32),
                ("mode", I32),
                ("event_id2", I32),
                ("event_num2", I32),
                ("params", ListI64),
                ("strings", ListStr),
                ("option", I64),
                ("message", I32),
                ("zone_id", I32),
            ],
        },
        Table {
            name: "log_changes",
            columns: &[
                ("port", I32),
                ("log", Str),
                ("area", Str),
                ("field", I32),
                ("old", I64),
                ("new", I64),
                ("id", I32),
                ("action", Str),
                ("event_idx", I64),
                ("event_id", I32),
                ("zone_id", I32),
            ],
        },
    ],
    sparse: true,
};

const NUM: [&str; 9] = ["num[0]", "num[1]", "num[2]", "num[3]", "num[4]", "num[5]", "num[6]", "num[7]", "num[8]"];
const DATA: [&str; 8] = ["Data[0]", "Data[1]", "Data[2]", "Data[3]", "Data[4]", "Data[5]", "Data[6]", "Data[7]"];
const LOG: [&str; 8] = ["data[0]", "data[1]", "data[2]", "data[3]", "data[4]", "data[5]", "data[6]", "data[7]"];
const NUM1: [&str; 4] = ["Num1[0]", "Num1[1]", "Num1[2]", "Num1[3]"];
const NUM2: [&str; 8] = ["Num2[0]", "Num2[1]", "Num2[2]", "Num2[3]", "Num2[4]", "Num2[5]", "Num2[6]", "Num2[7]"];

/// The fields at these paths, 0 where absent.
fn nums(f: &Decoded, paths: &[&str]) -> Vec<Option<i64>> {
    paths.iter().map(|p| Some(f.int(p).unwrap_or(0))).collect()
}

fn texts(f: &Decoded, paths: &[&str]) -> Vec<Option<String>> {
    paths.iter().map(|p| f.text(p)).collect()
}

/// An events row's own values; None where the packet gives none.
#[derive(Default)]
struct Ev {
    npc_id: Option<i64>,
    npc_index: Option<i64>,
    event_id: Option<i64>,
    event_num: Option<i64>,
    mode: Option<i64>,
    event_id2: Option<i64>,
    event_num2: Option<i64>,
    params: Option<Vec<Option<i64>>>,
    strings: Option<Vec<Option<String>>>,
    option: Option<i64>,
    message: Option<i64>,
}

#[derive(Default)]
pub struct Events {
    link: Link,
    resent: Resent,
    /// Port -> its last list.
    ports: HashMap<Option<i64>, [i64; 8]>,
}

impl Extractor for Events {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let key = p.key();
        if key == (S2C, 0x00A) {
            self.link.end();
            self.resent.zone_in(p.idx as i64);
            if f.flag("EventNum") {
                let e = Ev {
                    event_id: f.int("EventPara"),
                    event_num: f.int("EventNum"),
                    mode: f.int("EventMode"),
                    ..Ev::default()
                };
                self.emit(out, p, world, Kind::Start, e);
            }
            return;
        }
        if key == (S2C, 0x056) {
            self.log(p, f, world, out);
            return;
        }
        let Some(k) = kind(key) else { return };
        let (npc_id, npc_index) = (f.int("UniqueNo"), f.int("ActIndex"));
        let e = match k {
            Kind::Start => {
                let mut e = Ev {
                    npc_id,
                    npc_index,
                    event_id: f.int("EventPara"),
                    event_num: f.int("EventNum"),
                    mode: f.int("Mode"),
                    ..Ev::default()
                };
                if p.opcode == 0x033 {
                    e.strings = Some(texts(f, &["String1", "String2", "String3", "String4"]));
                    e.params = Some(nums(f, &DATA));
                } else {
                    (e.event_id2, e.event_num2) = (f.int("EventPara2"), f.int("EventNum2"));
                    if p.opcode == 0x034 {
                        e.params = Some(nums(f, &NUM[..8]));
                    }
                }
                e
            }
            _ if p.opcode == 0x05D => Ev {
                params: Some(nums(f, &NUM)),
                strings: Some(texts(f, &["string1", "string2", "string3", "string4"])),
                ..Ev::default()
            },
            Kind::Update => Ev { params: Some(nums(f, &NUM[..8])), ..Ev::default() },
            Kind::Reply => Ev {
                npc_id,
                npc_index,
                event_id: f.int("EventPara"),
                event_num: f.int("EventNum"),
                mode: f.int("Mode"),
                option: f.int("EndPara"),
                ..Ev::default()
            },
            Kind::Release => Ev { mode: f.int("Mode"), ..Ev::default() },
            Kind::Message if p.opcode == 0x053 => {
                Ev { message: f.int("Number"), params: Some(vec![f.int("para"), f.int("para2")]), ..Ev::default() }
            }
            Kind::Message => {
                let mut e =
                    Ev { npc_id, npc_index, message: Some(f.int("MesNum").unwrap_or(0) & 0x7FFF), ..Ev::default() };
                if p.opcode == 0x02A {
                    e.params = Some(nums(f, &NUM[..4]));
                    e.strings = Some(vec![f.text("String")]);
                } else if p.opcode == 0x027 {
                    let mut params = nums(f, &NUM1);
                    params.extend(nums(f, &NUM2));
                    e.params = Some(params);
                    e.strings = Some(texts(f, &["String1", "String2"]));
                }
                e
            }
        };
        self.emit(out, p, world, k, e);
        if k == Kind::Release {
            self.link.end();
        }
    }
}

impl Events {
    fn emit(&mut self, out: &mut Out, p: &Packet, world: &World, k: Kind, e: Ev) {
        let own = (k == Kind::Start).then_some(Start { idx: p.idx as i64, event_id: e.event_id });
        let start = self.link.see(p.ts_ms, own);
        out.emit(
            "events",
            Some(p),
            row! {
                kind: k.name(),
                opcode: p.opcode,
                event_idx: start.map(|s| s.idx),
                npc_id: e.npc_id,
                npc_index: e.npc_index,
                event_id: e.event_id,
                event_num: e.event_num,
                mode: e.mode,
                event_id2: e.event_id2,
                event_num2: e.event_num2,
                params: e.params,
                strings: e.strings,
                option: e.option,
                message: e.message,
                zone_id: world.zone,
            },
        );
    }

    fn log(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let port = f.int("Port");
        let new = LOG.map(|k| f.int(k).unwrap_or(0));
        let Some(old) = self.ports.insert(port, new) else { return };
        let start = self.resent.event(port.unwrap_or(-1), self.link.at(p.ts_ms));
        log_changes(port, &old, &new, |(log, area, field, a, b, id, action)| {
            out.emit(
                "log_changes",
                Some(p),
                row! {
                    port: port,
                    log: log,
                    area: area,
                    field: field,
                    old: a,
                    new: b,
                    id: id,
                    action: action,
                    event_idx: start.map(|s| s.idx),
                    event_id: start.and_then(|s| s.event_id),
                    zone_id: world.zone,
                },
            );
        });
    }
}

#[cfg(test)]
mod tests;
