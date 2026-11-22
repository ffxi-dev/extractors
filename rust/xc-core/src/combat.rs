//! combat.py: the action packet (0x028) as the combat extractors read it, which ids are mobs, which messages
//! mean a defeat, and how a resent packet is spotted.

use rustc_hash::FxHashMap as HashMap;

use crate::packet::{Fields, Packet};

pub const P: &str = "action (decoded bitstream).";
/// LSB msg_basic: DefeatsTarget, FallsToGround; captain's addons use both.
pub const DEFEAT: [i64; 2] = [6, 20];
/// hptrack: a packet whose payload repeats within this window is a resend.
pub const RESEND_MS: i64 = 500;

pub fn is_defeat(message: Option<i64>) -> bool {
    message.is_some_and(|m| DEFEAT.contains(&m))
}

/// A player: an id under 0x1000000.
pub fn is_player(id: Option<i64>) -> bool {
    id.is_some_and(|i| i < 0x1000000)
}

/// A trust or pet: an NPC id, 0x01ZZZIII, with an index the zone hands out, 0x700 on.
pub fn is_dynamic(id: Option<i64>) -> bool {
    id.is_some_and(|i| i >> 24 == 1 && (i & 0xFFF) >= 0x700)
}

/// A zone's own NPC or mob: id 0x01ZZZIII with index III under 0x400, as actionview's isMob.
pub fn is_mob(id: Option<i64>) -> bool {
    id.is_some_and(|i| i >> 24 == 1 && (i & 0xFFF) < 0x400)
}

/// An added effect (proc) or reaction (react): combat.EXTRA.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Extra {
    pub kind: Option<i64>,
    pub info: Option<i64>,
    pub value: Option<i64>,
    pub message: Option<i64>,
}

/// One result on a target: combat.RESULT, then proc and react, None when it has none.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActResult {
    pub miss: Option<i64>,
    pub kind: Option<i64>,
    pub sub_kind: Option<i64>,
    pub info: Option<i64>,
    pub scale: Option<i64>,
    pub value: Option<i64>,
    pub message: Option<i64>,
    pub bit: Option<i64>,
    pub proc: Option<Extra>,
    pub react: Option<Extra>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Target {
    pub id: Option<i64>,
    pub results: Vec<ActResult>,
}

/// combat.action's dict: actor, category (cmd_no), cmd_arg, info, and each target's results.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Action {
    pub actor_id: Option<i64>,
    pub cmd_no: Option<i64>,
    pub cmd_arg: Option<i64>,
    pub info: Option<i64>,
    pub targets: Vec<Target>,
}

impl Action {
    /// The first target's first result, which actions reads message and animation from.
    pub fn first(&self) -> Option<&ActResult> {
        self.targets.first()?.results.first()
    }
}

/// combat.action, field by field through the decoder's paths.
pub fn action_by_path<F: Fields + ?Sized>(f: &F) -> Action {
    let g = |k: &str| f.int(&format!("{P}{k}"));
    let mut a = Action {
        actor_id: g("actor_id"),
        cmd_no: g("cmd_no"),
        cmd_arg: g("cmd_arg"),
        info: g("info"),
        targets: Vec::new(),
    };
    for t in 0..g("target_count").unwrap_or(0) {
        let tp = format!("{P}targets[{t}]");
        let mut results = Vec::new();
        for i in 0..f.int(&format!("{tp}.result_count")).unwrap_or(0) {
            let rp = format!("{tp}[{i}].");
            let r = |k: &str| f.int(&format!("{rp}{k}"));
            let extra = |g: &str| {
                r(&format!("{g}.message")).map(|_| Extra {
                    kind: r(&format!("{g}.kind")),
                    info: r(&format!("{g}.info")),
                    value: r(&format!("{g}.value")),
                    message: r(&format!("{g}.message")),
                })
            };
            results.push(ActResult {
                miss: r("miss"),
                kind: r("kind"),
                sub_kind: r("sub_kind"),
                info: r("info"),
                scale: r("scale"),
                value: r("value"),
                message: r("message"),
                bit: r("bit"),
                proc: extra("proc"),
                react: extra("react"),
            });
        }
        a.targets.push(Target { id: f.int(&format!("{tp}.target_id")), results });
    }
    a
}

/// Spots a resent packet: the same bytes after the sync counter within RESEND_MS, as hptrack does.
#[derive(Default)]
pub struct Resends {
    seen: HashMap<Vec<u8>, i64>,
}

impl Resends {
    pub fn is_resend(&mut self, p: &Packet) -> bool {
        let key = p.data.get(4..).unwrap_or(&[]);
        let at = self.seen.insert(key.to_vec(), p.ts_ms);
        if self.seen.len() > 4096 {
            self.seen.retain(|_, t| p.ts_ms - *t < RESEND_MS);
        }
        at.is_some_and(|at| p.ts_ms - at < RESEND_MS)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ids() {
        let mob = 0x01000000 | (0x0A3 << 12) | 0x010;
        assert!(is_mob(Some(mob)) && !is_player(Some(mob)) && !is_dynamic(Some(mob)));
        assert!(is_dynamic(Some(0x01000000 | 0x700)) && !is_mob(Some(0x01000000 | 0x700)));
        assert!(is_player(Some(1)) && !is_mob(None) && !is_player(None));
    }

    #[test]
    fn resends() {
        let mut r = Resends::default();
        let data: &[u8] = &[1, 2, 3, 4, 9, 9];
        let other: &[u8] = &[5, 6, 7, 8, 9, 9]; // another sync counter, the same payload
        let at = |ts, data| Packet { idx: 0, ts_ms: ts, channel: 0, direction: 0, opcode: 0x28, flags: 0, data };
        assert!(!r.is_resend(&at(0, data)));
        assert!(r.is_resend(&at(499, other)));
        assert!(!r.is_resend(&at(999, data)));
    }
}
