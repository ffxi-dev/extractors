//! battle/immunity.py: each spell (0x028 category 4) on one of the zone's mobs, and whether it landed, was
//! resisted, or did nothing. Its Python twin keeps the docs.

use xc_core::combat::{Resends, is_mob};
use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{Decoded, Packet, S2C, World, row};

/// LSB msg_basic.
const IMMUNE: i64 = 655;
const RESIST: i64 = 85;
const RESIST_TARGET: i64 = 284;
const NO_EFFECT: i64 = 75;

pub static META: Meta = Meta {
    name: "immunity",
    version: 1,
    reads: &[(S2C, 0x028)],
    tables: &[Table {
        name: "spell_results",
        columns: &[
            ("caster_id", I64),
            ("target_id", I64),
            ("spell_id", I64),
            ("message", I32),
            ("outcome", Str),
            ("value", I64),
            ("zone_id", I32),
        ],
    }],
    sparse: true,
};

fn outcome(message: Option<i64>, bit: Option<i64>) -> &'static str {
    match message {
        Some(IMMUNE) => "immune",
        Some(RESIST) if bit.unwrap_or(0) & 0x02 != 0 => "trait_resist",
        Some(RESIST | RESIST_TARGET) => "resist",
        Some(NO_EFFECT) => "no_effect",
        _ => "landed",
    }
}

#[derive(Default)]
pub struct Immunity {
    resends: Resends,
}

impl Extractor for Immunity {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        if self.resends.is_resend(p) {
            return;
        }
        let a = f.action();
        if a.cmd_no != Some(4) || a.cmd_arg.unwrap_or(0) == 0 {
            return;
        }
        for t in a.targets.iter().filter(|t| is_mob(t.id)) {
            for r in &t.results {
                out.emit(
                    "spell_results",
                    Some(p),
                    row! {
                        caster_id: a.actor_id,
                        target_id: t.id,
                        spell_id: a.cmd_arg,
                        message: r.message,
                        outcome: outcome(r.message, r.bit),
                        value: r.value,
                        zone_id: world.zone,
                    },
                );
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::packets::{R, act, at, r};
    use xc_core::testing::{MOB, PLAYER, raw};

    /// test_combat.py's test_an_immunity_and_resists.
    #[test]
    fn an_immunity_and_resists() {
        let (mob2, other) = (MOB + 1, 0x0001_0002);
        let out = raw(
            Box::new(Immunity::default()),
            vec![
                at(0, act(PLAYER, 4, 253, &[(MOB, vec![r(655, 0)])])),
                at(10, act(PLAYER, 4, 253, &[(mob2, vec![R { bit: 2, ..r(85, 0) }])])),
                at(20, act(PLAYER, 4, 253, &[(mob2, vec![r(85, 0)])])),
                at(30, act(PLAYER, 4, 1, &[(other, vec![r(7, 50)])])), // a cure on a party member is not a mob's
            ],
            PLAYER,
        );
        let x = out.rows("spell_results");
        let got: Vec<_> =
            (0..x.len()).map(|i| (x.get(i, "target_id"), x.get(i, "spell_id"), x.get(i, "outcome"))).collect();
        let row = |t, o: &str| (V::Int(t), V::Int(253), V::Str(o.into()));
        assert_eq!(got, [row(MOB, "immune"), row(mob2, "trait_resist"), row(mob2, "resist")]);
    }

    #[test]
    fn outcomes() {
        assert_eq!(outcome(Some(284), None), "resist");
        assert_eq!(outcome(Some(75), None), "no_effect");
        assert_eq!(outcome(None, Some(2)), "landed");
    }
}
