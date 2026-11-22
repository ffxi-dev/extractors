//! battle/effects.py, line for line: the character's status effects as the zone lists them in 0x063 type 9,
//! each one's expiry, and the action that applied it. Its Python twin keeps the docs, and this keeps its name,
//! version, reads, and columns.

use xc_core::combat::{self, Resends};
use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::packet::Field;
use xc_core::vana::EPOCH_S;
use xc_core::{Decoded, Packet, S2C, World, py, row};

/// 0x063's expiry counts 60ths of a second from the Vana'diel epoch, in 32 bits.
pub const WRAP: i64 = 1 << 32;
/// An expiry that never comes.
const FOREVER: i64 = 0x7FFFFFFF;
const SAME_MS: i64 = 2000;
const BEFORE_MS: i64 = 3000;
const AFTER_MS: i64 = 1000;
const RELIST_MS: i64 = 60_000;
const ZONED_MS: i64 = 10_000;
const PAUSE_MS: i64 = 60_000;
/// Categories whose result value is the effect they gave: job abilities and items.
const ABILITY: [i64; 4] = [5, 6, 14, 15];
const PROC: [i64; 2] = [160, 164];
const MOVE: i64 = -1;
const KO: i64 = 0;
const SILENT_MS: i64 = 1500;
const PARALYZED: i64 = 84;
const HOUR_MS: i64 = 3_600_000;

/// Results whose value is the effect they gave.
fn landed(message: Option<i64>) -> bool {
    matches!(
        message,
        Some(
            82
            | 127
            | 141
            | 186
            | 194
            | 230
            | 236
            | 237
            | 242
            | 243
            | 266..=272
            | 277..=280
            | 319
            | 320
            | 375
            | 412
            | 645
            | 754
            | 755
            | 804,
        )
    )
}

/// The client's ailments: effects.py's AILMENTS.
fn ailment(status: i64) -> bool {
    matches!(
        status,
        1..=23 | 28..=31 | 128..=142 | 144..=149 | 156 | 167 | 168 | 174 | 175 | 177 | 189 | 404 | 473 | 572 | 576
            | 597 | 630 | 631
    )
}

pub static META: Meta = Meta {
    name: "effects",
    version: 9,
    sparse: true,
    reads: &[(S2C, 0x063), (S2C, 0x028), (S2C, 0x00A)],
    tables: &[Table {
        name: "effects",
        columns: &[
            ("status_id", I32),
            ("expires_ms", I64),
            ("duration_ms", I64),
            ("ended_ms", I64),
            ("renewed", Bool),
            ("source_idx", I64),
            ("named", Bool),
            ("source_ms", I64),
            ("actor_id", I64),
            ("actor_name", Str),
            ("category", I32),
            ("action_id", I64),
            ("message", I32),
            ("zone_id", I32),
        ],
    }],
};

static SERVER_S: Field = Field::new(S2C, 0x00A, "ntTimeSec");
static TYPE: Field = Field::new(S2C, 0x063, "type");
macro_rules! slots {
    ($($k:literal)*) => {
        [$((
            Field::new(S2C, 0x063, concat!("data.icon[", $k, "]")),
            Field::new(S2C, 0x063, concat!("data.timestamp[", $k, "]")),
        )),*]
    };
}
/// The status list's 32 slots: (icon, expiry).
static SLOTS: [(Field, Field); 32] =
    slots!(0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31);

/// effects.clock_offset over (status, expires, ended): how far the server's clock ran ahead, in whole hours.
pub fn clock_offset(rows: impl Iterator<Item = (i64, Option<i64>, Option<i64>)>) -> i64 {
    let gaps: Vec<i64> = rows.filter(|&(s, _, _)| s != KO).filter_map(|(_, e, d)| Some(e? - d?)).collect();
    // Counter in first-seen order: most_common(1) takes the first of the most.
    let mut hours: Vec<(i64, usize)> = Vec::new();
    for &g in &gaps {
        let h = py::round(g as f64 / HOUR_MS as f64);
        if (g - h * HOUR_MS).abs() <= 60_000 {
            match hours.iter_mut().find(|(x, _)| *x == h) {
                Some((_, n)) => *n += 1,
                None => hours.push((h, 1)),
            }
        }
    }
    let Some(&(h, n)) = hours.iter().fold(None, |best: Option<&(i64, usize)>, x| match best {
        Some(b) if b.1 >= x.1 => Some(b),
        _ => Some(x),
    }) else {
        return 0;
    };
    let fits = gaps.iter().filter(|&&g| g >= h * HOUR_MS - 60_000).count();
    if n >= 3 && fits as f64 >= 0.8 * gaps.len() as f64 { h * HOUR_MS } else { 0 }
}

/// 0x063's expiry in Unix ms, read as the nearest to the packet's time; None for FOREVER.
pub fn expiry_ms(raw: i64, now_ms: i64) -> Option<i64> {
    if raw == FOREVER {
        return None;
    }
    let base = (now_ms as f64 / 1000.0 - EPOCH_S as f64) * 60.0;
    let n = raw + py::round((base - raw as f64) / WRAP as f64) * WRAP;
    Some(((n as f64 / 60.0 + EPOCH_S as f64) * 1000.0) as i64)
}

/// The action a result came from: effects.py's src.
#[derive(Clone, Debug, Default)]
struct Src {
    idx: i64,
    ts_ms: i64,
    actor_id: Option<i64>,
    category: Option<i64>,
    action_id: Option<i64>,
    message: Option<i64>,
}

/// A recent result on the character: (ts, status, sure, source). status None gives any icon; MOVE, an ailment.
#[derive(Clone, Debug)]
struct Landed {
    ts: i64,
    status: Option<i64>,
    sure: bool,
    src: Src,
}

/// An effects row, as the Python dict an extractor changes until the end.
#[derive(Clone, Debug)]
struct Row {
    idx: u64,
    ts_ms: i64,
    status_id: i64,
    expires_ms: Option<i64>,
    duration_ms: Option<i64>,
    ended_ms: Option<i64>,
    renewed: bool,
    zone_id: Option<i64>,
    src: Option<Src>,
    named: Option<bool>,
    actor_name: Option<String>,
    /// The expiry the list gives it now: Python's self.listed[id(row)].
    listed: Option<i64>,
    /// The clock offset in force when it was listed.
    off: Option<i64>,
}

#[derive(Default)]
pub struct Effects {
    /// Every row, in emit order; held, gone, and waiting index it.
    rows: Vec<Row>,
    held: Vec<usize>,
    gone: Vec<usize>,
    landed: Vec<Landed>,
    waiting: Vec<usize>,
    zoned_at: Option<i64>,
    off: Option<i64>,
    resends: Resends,
    /// This packet's (status, expires), kept for its allocation.
    listed: Vec<(i64, Option<i64>)>,
}

impl Extractor for Effects {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, _out: &mut Out) {
        match p.opcode {
            0x00A => {
                self.zoned_at = Some(p.ts_ms);
                // The server's Unix seconds: the offset in whole hours, at once.
                if let Some(now) = SERVER_S.int(f).filter(|&n| n != 0) {
                    self.off = Some(py::round((now * 1000 - p.ts_ms) as f64 / HOUR_MS as f64) * HOUR_MS);
                }
            }
            0x028 => self.results(p, f, world),
            _ if TYPE.int(f) == Some(9) => self.icons(p, f, world),
            _ => {}
        }
    }

    fn finish(&mut self, world: &World, out: &mut Out) {
        for i in std::mem::take(&mut self.waiting) {
            self.claim(i, world, true);
        }
        let first = self.rows.iter().find_map(|r| r.off);
        let guess =
            first.unwrap_or_else(|| clock_offset(self.rows.iter().map(|r| (r.status_id, r.expires_ms, r.ended_ms))));
        for r in &mut self.rows {
            let off = r.off.unwrap_or(guess);
            if off != 0
                && let (Some(e), Some(d)) = (r.expires_ms, r.duration_ms)
            {
                (r.expires_ms, r.duration_ms) = (Some(e - off), Some(d - off));
            }
            let at =
                Packet { idx: r.idx, ts_ms: r.ts_ms, channel: 0, direction: S2C, opcode: 0x063, flags: 0, data: &[] };
            let s = r.src.clone().unwrap_or_default();
            let has = r.src.is_some();
            out.emit(
                "effects",
                Some(&at),
                row! {
                    status_id: r.status_id,
                    expires_ms: r.expires_ms,
                    duration_ms: r.duration_ms,
                    ended_ms: r.ended_ms,
                    renewed: r.renewed,
                    source_idx: has.then_some(s.idx),
                    named: r.named,
                    source_ms: has.then_some(s.ts_ms),
                    actor_id: s.actor_id,
                    actor_name: r.actor_name.take(),
                    category: s.category,
                    action_id: s.action_id,
                    message: s.message,
                    zone_id: r.zone_id,
                },
            );
        }
    }
}

impl Effects {
    fn results(&mut self, p: &Packet, f: &Decoded, world: &World) {
        let me = world.character_id.filter(|&m| m != 0);
        if me.is_none() || self.resends.is_resend(p) {
            return;
        }
        let a = f.action();
        let cat = a.cmd_no;
        let src = Src {
            idx: p.idx as i64,
            ts_ms: p.ts_ms,
            actor_id: a.actor_id,
            category: cat,
            action_id: a.cmd_arg,
            message: None,
        };
        let ability = cat.is_some_and(|c| ABILITY.contains(&c));
        let mob = combat::is_mob(a.actor_id);
        let at = |status, sure, message| Landed { ts: p.ts_ms, status, sure, src: Src { message, ..src.clone() } };
        for t in a.targets.iter().filter(|t| t.id == me) {
            for r in &t.results {
                let sure = landed(r.message);
                if sure || ability {
                    self.landed.push(at(r.value, sure, r.message));
                }
                if let Some(x) = r.proc.as_ref().filter(|x| x.message.is_some_and(|m| PROC.contains(&m))) {
                    self.landed.push(at(x.value, true, x.message));
                }
                let went = r.miss.is_none_or(|m| m == 0) && r.message != Some(PARALYZED);
                if ability && !mob {
                    self.landed.push(at(None, false, r.message));
                } else if matches!(cat, Some(4 | 11)) && mob && went {
                    self.landed.push(at(Some(MOVE), false, r.message));
                }
            }
        }
        // A row waits AFTER_MS for a result that names it; then it settles for an item or a silent move.
        for i in std::mem::take(&mut self.waiting) {
            let late = p.ts_ms - self.rows[i].ts_ms > AFTER_MS;
            if !self.claim(i, world, late) && !late {
                self.waiting.push(i);
            }
        }
        self.landed.retain(|x| p.ts_ms - x.ts <= BEFORE_MS);
    }

    /// effects.py's _claim: fill row i's source from the results near its icon.
    fn claim(&mut self, i: usize, world: &World, settle: bool) -> bool {
        let (status, at, renewed) = (self.rows[i].status_id, self.rows[i].ts_ms, self.rows[i].renewed);
        if status == KO {
            return false;
        }
        let near = |x: &Landed| at - BEFORE_MS <= x.ts && x.ts <= at + AFTER_MS;
        // max() keeps the first of the greatest.
        let mut best: Option<usize> = None;
        for (k, x) in self.landed.iter().enumerate() {
            if near(x) && x.status == Some(status) {
                let y = best.map(|b| &self.landed[b]);
                if y.is_none_or(|y| (x.sure, x.ts) > (y.sure, y.ts)) {
                    best = Some(k);
                }
            }
        }
        let named = best.is_some();
        if !named {
            if !settle || renewed {
                return false;
            }
            let ail = ailment(status);
            for (k, x) in self.landed.iter().enumerate() {
                let other = (x.status.is_none() && !ail) || (x.status == Some(MOVE) && x.ts >= at - SILENT_MS && ail);
                if near(x) && other {
                    let y = best.map(|b| &self.landed[b]);
                    if y.is_none_or(|y| (x.status.is_none(), x.ts) > (y.status.is_none(), y.ts)) {
                        best = Some(k);
                    }
                }
            }
        }
        let Some(b) = best else { return false };
        let src = self.landed[b].src.clone();
        let row = &mut self.rows[i];
        if row.expires_ms.is_some_and(|e| e - self.off.unwrap_or(0) <= src.ts_ms) {
            return false;
        }
        if let Some(e) = row.expires_ms {
            row.duration_ms = Some(e - src.ts_ms);
        }
        row.named = Some(named);
        row.actor_name = if combat::is_mob(src.actor_id) { world.name(src.actor_id).map(str::to_string) } else { None };
        // The result is spent, and so is an item's claim to any icon; a silent move may give several.
        let best_move = self.landed[b].status == Some(MOVE);
        let mut k = 0;
        self.landed.retain(|x| {
            let spent = (k == b && !best_move) || (x.status.is_none() && x.src.idx == src.idx);
            k += 1;
            !spent
        });
        row.src = Some(src);
        true
    }

    fn icons(&mut self, p: &Packet, f: &Decoded, world: &World) {
        self.listed.clear();
        for (icon, stamp) in SLOTS.iter() {
            let (Some(icon), raw) = (icon.int(f), stamp.int(f)) else { continue };
            if icon != 0xFF && icon != 0xFFFF && (icon != 0 || raw.is_some_and(|r| r != 0)) {
                self.listed.push((icon, expiry_ms(raw.unwrap_or(0), p.ts_ms)));
            }
        }
        let mut held = std::mem::take(&mut self.held);
        let pause = if self.zoned_at.is_some_and(|z| p.ts_ms - z <= ZONED_MS) { PAUSE_MS } else { SAME_MS };
        for n in 0..self.listed.len() {
            let (status, expires) = self.listed[n];
            let taken = take(&self.rows, &mut held, status, expires, pause)
                .or_else(|| take(&self.rows, &mut self.gone, status, expires, pause));
            let i = match taken {
                Some(i) => i,
                None => {
                    let old = held.iter().position(|&r| self.rows[r].status_id == status);
                    if let Some(o) = old {
                        let r = held.remove(o);
                        self.rows[r].ended_ms = Some(p.ts_ms);
                    }
                    self.rows.push(Row {
                        idx: p.idx,
                        ts_ms: p.ts_ms,
                        status_id: status,
                        expires_ms: expires,
                        duration_ms: expires.map(|e| e - p.ts_ms),
                        ended_ms: None,
                        renewed: old.is_some(),
                        zone_id: world.zone,
                        src: None,
                        named: None,
                        actor_name: None,
                        listed: None,
                        off: self.off,
                    });
                    let i = self.rows.len() - 1;
                    if !self.claim(i, world, false) {
                        self.waiting.push(i);
                    }
                    i
                }
            };
            (self.rows[i].ended_ms, self.rows[i].listed) = (None, expires);
            self.held.push(i);
        }
        for &r in &held {
            self.rows[r].ended_ms = Some(p.ts_ms);
        }
        // Expiries count by the server's clock, packet times by the capture's.
        let off = self.off.unwrap_or(0);
        let rows = &self.rows;
        let until = |r: usize| match rows[r].listed {
            Some(l) if l != 0 => l - off,
            _ => rows[r].ended_ms.expect("a row gone has ended") + RELIST_MS,
        };
        self.gone.extend(held);
        self.gone.retain(|&r| until(r) > p.ts_ms);
    }
}

/// effects._take: the row in rows for this icon and expiry, removed from them: listed last with the same
/// expiry, or one moved by -SAME_MS to pause.
fn take(all: &[Row], rows: &mut Vec<usize>, status: i64, expires: Option<i64>, pause: i64) -> Option<usize> {
    let k = rows.iter().position(|&r| {
        let (r, was) = (&all[r], all[r].listed);
        r.status_id == status
            && (was == expires || matches!((expires, was), (Some(e), Some(w)) if -SAME_MS <= e - w && e - w <= pause))
    })?;
    Some(rows.remove(k))
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MEMBER, MapFields, PLAYER, drive};

    const P: &str = combat::P;
    const T0: i64 = 1_792_000_000_000;
    const ZONE: i64 = 0x0BE;
    const MOB: i64 = 0x01000000 | (ZONE << 12) | 0x020;
    const POISON: i64 = 3;
    const FOOD: i64 = 251;
    const PROTECT: i64 = 40;

    type Step = (u16, MapFields);

    fn raw(expires_ms: i64) -> i64 {
        py::intmod(((expires_ms as f64 / 1000.0 - EPOCH_S as f64) * 60.0) as i64, WRAP)
    }

    /// A status list: (status, expires_ms, None for no end, Some(0) for none) each.
    fn icons(listed: &[(i64, Option<i64>)]) -> Step {
        let mut f = MapFields::new().int("type", 9);
        for k in 0..32 {
            let (status, expires) = listed.get(k).copied().unwrap_or((0xFF, Some(0)));
            let stamp = match expires {
                None => FOREVER,
                Some(0) => 0,
                Some(e) => raw(e),
            };
            f = f.int(&format!("data.icon[{k}]"), status).int(&format!("data.timestamp[{k}]"), stamp);
        }
        (0x063, f)
    }

    fn act(cat: i64, arg: i64, message: i64, value: i64, actor: i64) -> MapFields {
        MapFields::new()
            .int(&format!("{P}actor_id"), actor)
            .int(&format!("{P}cmd_no"), cat)
            .int(&format!("{P}cmd_arg"), arg)
            .int(&format!("{P}target_count"), 1)
            .int(&format!("{P}targets[0].target_id"), PLAYER)
            .int(&format!("{P}targets[0].result_count"), 1)
            .int(&format!("{P}targets[0][0].message"), message)
            .int(&format!("{P}targets[0][0].value"), value)
    }

    fn action(cat: i64, arg: i64, message: i64, value: i64) -> Step {
        (0x028, act(cat, arg, message, value, MOB))
    }

    fn by(actor: i64, cat: i64, arg: i64, message: i64, value: i64) -> Step {
        (0x028, act(cat, arg, message, value, actor))
    }

    fn bat() -> Step {
        (0x00E, MapFields::new().int("UniqueNo", MOB).int("ActIndex", 0x020).text("Data.name", "LocusDireBat"))
    }

    fn zone_in(now_s: i64) -> Step {
        (0x00A, MapFields::new().int("ntTimeSec", now_s))
    }

    struct Got(xc_core::Out);

    impl Got {
        fn len(&self) -> usize {
            self.0.rows("effects").len()
        }
        fn get(&self, i: usize, k: &str) -> V {
            self.0.rows("effects").get(i, k)
        }
        fn row(&self, i: usize, ks: &[&str]) -> Vec<V> {
            ks.iter().map(|k| self.get(i, k)).collect()
        }
        fn col(&self, k: &str) -> Vec<V> {
            (0..self.len()).map(|i| self.get(i, k)).collect()
        }
    }

    fn effects(steps: Vec<Step>, times: Vec<i64>) -> Got {
        Got(drive(&mut Effects::default(), steps, Drive { times: Some(times), ..Drive::default() }))
    }

    fn v<T: Into<V>>(x: T) -> V {
        x.into()
    }

    #[test]
    fn the_duration_is_what_the_status_list_gave_from_the_move_that_applied_it() {
        let hit = T0 + 1000;
        let g = effects(
            vec![bat(), action(11, 392, 242, POISON), icons(&[(POISON, Some(hit + 180_000))])],
            vec![T0, hit, hit + 600],
        );
        assert_eq!(g.len(), 1);
        let ks = ["status_id", "duration_ms", "category", "action_id", "actor_name", "source_idx"];
        assert_eq!(g.row(0, &ks), vec![v(POISON), v(180_000), v(11), v(392), v("LocusDireBat"), v(1)]);
        assert_eq!(g.row(0, &["renewed", "ended_ms"]), vec![v(false), V::Null]);
    }

    #[test]
    fn an_icon_listed_before_its_action_and_an_added_effect() {
        let hit = T0 + 1000;
        let (op, f) = action(1, 0, 1, POISON);
        let f =
            f.int(&format!("{P}targets[0][0].proc.message"), 160).int(&format!("{P}targets[0][0].proc.value"), POISON);
        let g = effects(vec![bat(), icons(&[(POISON, Some(hit + 30_000))]), (op, f)], vec![T0, hit - 300, hit]);
        assert_eq!(g.row(0, &["category", "message", "duration_ms"]), vec![v(1), v(160), v(30_000)]);
    }

    #[test]
    fn a_move_that_gives_its_effects_silently() {
        let hit = T0 + 1000;
        let g = effects(
            vec![
                bat(),
                action(11, 4189, 264, 348),
                by(MEMBER, 4, 1, 7, 145),
                icons(&[(145, Some(hit + 45_000)), (11, Some(hit + 45_000))]),
            ],
            vec![T0, hit, hit + 300, hit + 700],
        );
        let ks = ["status_id", "action_id", "named", "actor_name", "duration_ms"];
        assert_eq!(g.row(0, &ks), vec![v(145), v(4189), v(false), v("LocusDireBat"), v(45_000)]);
        assert_eq!(g.row(1, &ks), vec![v(11), v(4189), v(false), v("LocusDireBat"), v(45_000)]);
        // An icon that renews itself every few seconds takes no move that happened to hit just before.
        let g = effects(
            vec![
                bat(),
                icons(&[(404, Some(hit + 5_000))]),
                action(11, 4189, 264, 348),
                icons(&[(404, Some(hit + 10_000))]),
            ],
            vec![T0, hit, hit + 4_400, hit + 5_000],
        );
        assert_eq!((g.get(1, "renewed"), g.get(1, "source_idx"), g.get(0, "source_idx")), (v(true), V::Null, V::Null));
        // A bard's March names its icon over a move 500 ms before; a second March icon no result names is none's.
        let g = effects(
            vec![
                bat(),
                action(11, 4189, 264, 348),
                icons(&[(214, Some(hit + 120_000))]),
                by(MEMBER, 4, 419, 266, 214),
                action(11, 4189, 264, 348),
                icons(&[(214, Some(hit + 120_000)), (214, Some(hit + 130_000))]),
            ],
            vec![T0, hit - 500, hit, hit + 400, hit + 9_500, hit + 10_000],
        );
        assert_eq!((g.get(0, "category"), g.get(0, "named"), g.get(1, "source_idx")), (v(4), v(true), V::Null));
        // KO is the defeat, which no move gives as an effect.
        let g =
            effects(vec![bat(), action(4, 0, 252, 0), icons(&[(0, Some(hit + 3_600_000))])], vec![T0, hit, hit + 500]);
        assert_eq!((g.len(), g.get(0, "status_id"), g.get(0, "source_idx")), (1, v(0), V::Null));
    }

    #[test]
    fn a_silent_move_lands_and_gives_no_buff() {
        let hit = T0 + 1000;
        let g = effects(
            vec![bat(), action(11, 628, 185, 300), icons(&[(42, Some(hit + 120_000))])],
            vec![T0, hit, hit + 1000],
        );
        assert_eq!((g.len(), g.get(0, "source_idx")), (1, V::Null));
        let (op, f) = action(11, 629, 188, 0);
        let missed = (op, f.int(&format!("{P}targets[0][0].miss"), 1));
        let g = effects(vec![bat(), missed, icons(&[(10, Some(hit + 7_000))])], vec![T0, hit, hit + 500]);
        assert_eq!((g.len(), g.get(0, "source_idx")), (1, V::Null));
    }

    #[test]
    fn a_capture_an_hour_behind_the_server() {
        let (hit, ahead) = (T0 + 1000, 3_600_000);
        let g = effects(
            vec![
                bat(),
                action(11, 629, 185, 300),
                icons(&[(10, Some(hit + ahead + 7_000))]),
                icons(&[]),
                icons(&[(POISON, Some(hit + ahead + 30_000))]),
                icons(&[]),
                icons(&[(PROTECT, Some(hit + ahead + 60_000))]),
                icons(&[]),
            ],
            vec![T0, hit, hit + 300, hit + 7_400, hit + 8_000, hit + 30_300, hit + 31_000, hit + 60_200],
        );
        assert_eq!(g.col("status_id"), vec![v(10), v(POISON), v(PROTECT)]);
        assert_eq!(g.col("duration_ms"), vec![v(7_000), v(30_000 - 8_000), v(60_000 - 31_000)]);
        assert_eq!(g.get(0, "expires_ms"), v(hit + 7_000));
        // Two ended icons, an hour apart: too few to tell, so nothing is set back.
        let g = effects(
            vec![icons(&[(PROTECT, Some(T0 + ahead))]), icons(&[]), icons(&[(FOOD, Some(T0 + 60_000))]), icons(&[])],
            vec![T0, T0 + 1000, T0 + 2000, T0 + 60_000],
        );
        assert_eq!(g.get(0, "expires_ms"), v(T0 + ahead));
    }

    #[test]
    fn a_capture_hours_ahead_of_the_server_keeps_its_sources() {
        let (hit, behind) = (T0 + 1000, 9 * 3_600_000);
        let g = effects(
            vec![
                zone_in((T0 - behind) / 1000),
                bat(),
                action(11, 392, 242, POISON),
                icons(&[(POISON, Some(hit - behind + 180_000))]),
            ],
            vec![T0, T0, hit, hit + 600],
        );
        assert_eq!(g.row(0, &["source_idx", "duration_ms", "expires_ms"]), vec![v(2), v(180_000), v(hit + 180_000)]);
    }

    #[test]
    fn a_capture_across_a_clock_change_sets_each_icon_back_by_its_own_offset() {
        let (hit, hour) = (T0 + 1000, 3_600_000);
        let later = hit + 86_400_000;
        let g = effects(
            vec![
                zone_in((T0 + hour) / 1000),
                bat(),
                action(11, 392, 242, POISON),
                icons(&[(POISON, Some(hit + hour + 30_000))]),
                icons(&[]),
                zone_in((later - 1000) / 1000),
                bat(),
                action(11, 392, 242, POISON),
                icons(&[(POISON, Some(later + 30_000))]),
            ],
            vec![T0, T0, hit, hit + 300, hit + 30_000, later - 1000, later - 1000, later, later + 300],
        );
        assert_eq!(g.col("duration_ms"), vec![v(30_000), v(30_000)]);
    }

    #[test]
    fn a_roll_or_an_art_a_player_used_on_the_character_comes_before_a_silent_move() {
        let hit = T0 + 1000;
        let g = effects(
            vec![bat(), by(MEMBER, 6, 98, 420, 5), icons(&[(316, Some(hit + 300_000))]), action(11, 2039, 264, 0)],
            vec![T0, hit, hit + 227, hit + 574],
        );
        assert_eq!(g.row(0, &["category", "action_id", "actor_id", "named"]), vec![v(6), v(98), v(MEMBER), v(false)]);
        let g = effects(
            vec![bat(), action(4, 356, 264, 0), by(PLAYER, 6, 212, 100, 0), icons(&[(359, Some(hit + 7_200_000))])],
            vec![T0, hit - 761, hit, hit + 541],
        );
        assert_eq!(g.row(0, &["action_id", "actor_id"]), vec![v(212), v(PLAYER)]);
    }

    #[test]
    fn an_ability_that_names_nothing_gives_no_ailment() {
        let hit = T0 + 1000;
        let g = effects(
            vec![
                bat(),
                by(PLAYER, 6, 212, 100, 0),
                action(4, 267, 330, 0),
                icons(&[(137, Some(hit + 34_000)), (359, Some(hit + 7_200_000))]),
            ],
            vec![T0, hit - 981, hit - 700, hit],
        );
        assert_eq!(g.row(0, &["action_id", "actor_name"]), vec![v(267), v("LocusDireBat")]);
        assert_eq!(g.row(1, &["action_id", "actor_id"]), vec![v(212), v(PLAYER)]);
    }

    #[test]
    fn a_paralyzed_mob_gives_nothing() {
        let hit = T0 + 1000;
        let g =
            effects(vec![bat(), action(4, 0, 84, 0), icons(&[(198, Some(hit + 264_000))])], vec![T0, hit, hit + 1000]);
        assert_eq!((g.len(), g.get(0, "source_idx")), (1, V::Null));
    }

    #[test]
    fn a_silent_move_gives_only_an_ailment() {
        let hit = T0 + 1000;
        let listed = icons(&[
            (135, Some(hit + 117_000)),
            (198, Some(hit + 257_000)),
            (317, Some(hit + 201_000)),
            (321, Some(hit + 145_000)),
        ]);
        let g = effects(vec![bat(), action(4, 172, 2, 120), listed], vec![T0, hit, hit]);
        assert_eq!(g.col("status_id"), vec![v(135), v(198), v(317), v(321)]);
        assert_eq!(g.col("action_id"), vec![v(172), V::Null, V::Null, V::Null]);
    }

    #[test]
    fn icons_cleared_early_count_against_no_clock_offset() {
        let hour = 3_600_000;
        let lasts = [7_000, 30_000, 60_000, 90_000, 120_000];
        let ends = [7_000, 30_000, 60_000, 10_000, 20_000];
        let (mut steps, mut times) = (vec![], vec![]);
        for k in 0..5 {
            let t = T0 + k as i64 * 200_000;
            steps.extend([icons(&[(POISON, Some(t - hour + lasts[k]))]), icons(&[])]);
            times.extend([t, t + ends[k]]);
        }
        assert_eq!(effects(steps, times).col("duration_ms"), lasts.map(v).to_vec());
    }

    #[test]
    fn a_renewal_a_zone_in_and_the_end() {
        let (first, again) = (T0, T0 + 600_000);
        let cast = || by(MEMBER, 4, 43, 230, PROTECT);
        let g = effects(
            vec![
                cast(),
                icons(&[(PROTECT, Some(first + 1_800_000))]),
                cast(),
                icons(&[(PROTECT, Some(again + 1_800_000))]),
                (0x00A, MapFields::new().int("ZoneNo", ZONE)),
                icons(&[]),
                icons(&[(PROTECT, Some(again + 1_804_000))]),
                icons(&[]),
            ],
            vec![
                first,
                first + 500,
                again,
                again + 500,
                again + 60_000,
                again + 60_100,
                again + 62_000,
                T0 + 2_404_000,
            ],
        );
        assert_eq!(g.len(), 2);
        assert_eq!(g.row(0, &["renewed", "ended_ms", "duration_ms"]), vec![v(false), v(again + 500), v(1_800_000)]);
        assert_eq!(g.row(1, &["renewed", "ended_ms", "actor_id"]), vec![v(true), v(T0 + 2_404_000), v(MEMBER)]);
    }

    #[test]
    fn food_takes_the_item_eaten_and_an_unclaimed_icon_has_no_source() {
        let g = effects(
            vec![
                by(PLAYER, 5, 4422, 0, 0),
                icons(&[(FOOD, Some(T0 + 1_800_000))]),
                icons(&[(FOOD, Some(T0 + 1_800_000)), (143, None)]),
            ],
            vec![T0, T0 + 700, T0 + 900],
        );
        let ks = ["status_id", "category", "action_id", "source_idx", "expires_ms", "duration_ms"];
        assert_eq!(g.row(0, &ks), vec![v(FOOD), v(5), v(4422), v(0), v(T0 + 1_800_000), v(1_800_000)]);
        assert_eq!(g.row(1, &ks), vec![v(143), V::Null, V::Null, V::Null, V::Null, V::Null]);
    }

    #[test]
    fn the_expiry_wraps_every_two_years() {
        let now = T0 + 5_000;
        assert_eq!(expiry_ms(raw(now + 90_000), now), Some(now + 90_000));
        let later = (EPOCH_S + (WRAP * 3 + 7) / 60) * 1000;
        assert_eq!(expiry_ms(raw(later + 60_000), later), Some(later + 60_000));
    }
}
