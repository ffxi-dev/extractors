//! battle/defeats.py: each time the character was defeated, and by whom (0x029 97 or 20).

use xc_core::combat::{Resends, is_mob};
use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

static CASTER: Field = Field::new(S2C, 0x029, "UniqueNoCas");
static TARGET: Field = Field::new(S2C, 0x029, "UniqueNoTar");
static MESSAGE: Field = Field::new(S2C, 0x029, "MessageNum");

pub static META: Meta = Meta {
    name: "defeats",
    version: 1,
    reads: &[(S2C, 0x029)],
    tables: &[Table {
        name: "defeats",
        columns: &[("killer_id", I64), ("killer_name", Str), ("message", I32), ("zone_id", I32)],
    }],
    sparse: true,
};

#[derive(Default)]
pub struct Defeats {
    resends: Resends,
}

impl Extractor for Defeats {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let msg = MESSAGE.int(f);
        if !matches!(msg, Some(20 | 97)) || TARGET.int(f) != world.character_id || self.resends.is_resend(p) {
            return;
        }
        let killer = if msg == Some(97) { CASTER.int(f) } else { None };
        let name = if is_mob(killer) { world.name(killer) } else { None };
        out.emit("defeats", Some(p), row! { killer_id: killer, killer_name: name, message: msg, zone_id: world.zone });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MEMBER, MOB, MapFields, PLAYER, drive};

    fn msg(cas: i64, tar: i64, n: i64) -> (u16, MapFields) {
        (0x029, MapFields::new().int("UniqueNoCas", cas).int("UniqueNoTar", tar).int("MessageNum", n))
    }

    /// test_effects.py's test_the_characters_defeats.
    #[test]
    fn the_characters_defeats() {
        let bat = MapFields::new().int("UniqueNo", MOB).int("ActIndex", 0x010).text("Data.name", "LocusDireBat");
        let out = drive(
            &mut Defeats::default(),
            vec![
                (0x00E, bat),
                msg(MOB, PLAYER, 97),
                msg(PLAYER, PLAYER, 20),
                msg(PLAYER, MOB, 6), // the bat's defeat
                msg(MOB, MEMBER, 97),
            ],
            Drive::default(),
        );
        let r = out.rows("defeats");
        let got: Vec<_> =
            (0..r.len()).map(|i| (r.get(i, "message"), r.get(i, "killer_id"), r.get(i, "killer_name"))).collect();
        assert_eq!(got, [(V::Int(97), V::Int(MOB), V::Str("LocusDireBat".into())), (V::Int(20), V::Null, V::Null)]);
    }
}
