//! battle/evasion.py: the recording character's evasion skill, from its skills (0x062).

use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

static SKILL: Field = Field::new(S2C, 0x062, "skill_base[29]");

pub static META: Meta = Meta {
    name: "evasion_skill",
    version: 1,
    reads: &[(S2C, 0x062)],
    tables: &[Table { name: "evasion_skill", columns: &[("skill", I32)] }],
    sparse: true,
};

#[derive(Default)]
pub struct EvasionSkill;

impl Extractor for EvasionSkill {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, _world: &World, out: &mut Out) {
        if let Some(skill) = SKILL.int(f) {
            out.emit("evasion_skill", Some(p), row! { skill: skill & 0x7FFF });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MapFields, drive};

    #[test]
    fn the_rank_bit_is_masked_and_an_update_without_it_gives_none() {
        let out = drive(
            &mut EvasionSkill,
            vec![(0x062, MapFields::new().int("skill_base[29]", 0x8000 | 230)), (0x062, MapFields::new())],
            Drive::default(),
        );
        let rows = out.rows("evasion_skill");
        assert_eq!((rows.len(), rows.get(0, "skill")), (1, V::Int(230)));
    }
}
