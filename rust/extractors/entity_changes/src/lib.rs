//! world/entity_changes.py: each entity's first update in a capture (0x00E, or 0x00D for a player), then
//! each update that changes its name, model, or monster flag. Its Python twin keeps the docs.

use std::collections::HashMap;
use std::collections::hash_map::Entry;

use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, Value, World, row};

pub static META: Meta = Meta {
    name: "entity_changes",
    version: 1,
    reads: &[(S2C, 0x00E), (S2C, 0x00D)],
    sparse: false,
    tables: &[Table {
        name: "entity_changes",
        columns: &[
            ("entity_id", I64),
            ("act_index", I32),
            ("zone_id", I32),
            ("name", Str),
            ("monster", Bool),
            ("model_id", I32),
            ("x", F32),
            ("y", F32),
            ("z", F32),
        ],
    }],
};

/// The fields both updates carry, found once for each.
struct Of {
    uid: Field,
    act_index: Field,
    name: Field,
    position: Field,
    x: Field,
    y: Field,
    z: Field,
}

macro_rules! of {
    ($op:literal, $name:literal) => {
        Of {
            uid: Field::new(S2C, $op, "UniqueNo"),
            act_index: Field::new(S2C, $op, "ActIndex"),
            name: Field::new(S2C, $op, $name),
            position: Field::new(S2C, $op, "SendFlg.Position"),
            x: Field::new(S2C, $op, "x"),
            y: Field::new(S2C, $op, "y"),
            z: Field::new(S2C, $op, "z"),
        }
    };
}

static NPC: Of = of!(0x00E, "Data.name");
static PC: Of = of!(0x00D, "name");
static GENERAL: Field = Field::new(S2C, 0x00E, "SendFlg.General");
static MONSTER: Field = Field::new(S2C, 0x00E, "Flags1.MonsterFlag");
static SUB_KIND: Field = Field::new(S2C, 0x00E, "SubKind");
static MODEL_ID: Field = Field::new(S2C, 0x00E, "Data.model_id");

/// What an entity is known to be: each part the last update that sent it said.
#[derive(Default)]
struct Known {
    name: Option<String>,
    monster: Option<bool>,
    model: Option<i64>,
}

#[derive(Default)]
pub struct EntityChanges {
    known: HashMap<i64, Known>,
}

impl Extractor for EntityChanges {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let npc = p.opcode == 0x00E;
        let of = if npc { &NPC } else { &PC };
        let Some(uid) = of.uid.int(f) else { return };
        let text = of.name.get(f);
        let mut name = match &text {
            Some(Value::Text(s)) => Some(&**s),
            _ => None,
        };
        let (mut monster, mut model) = (None, None);
        if npc {
            name = name.or_else(|| world.entities.get(&of.act_index.int(f))?.name.as_deref());
            monster = GENERAL.flag(f).then(|| MONSTER.flag(f));
            // SendFlg.Model alone is a humanoid look.
            model = if SUB_KIND.int(f) == Some(0) { MODEL_ID.int(f) } else { None };
        }
        // Each part not sent keeps the one known; a row when any part sent differs from it.
        let k = match self.known.entry(uid) {
            Entry::Occupied(e) => {
                let k = e.into_mut();
                if name.is_none_or(|n| k.name.as_deref() == Some(n))
                    && monster.is_none_or(|m| k.monster == Some(m))
                    && model.is_none_or(|m| k.model == Some(m))
                {
                    return;
                }
                k
            }
            Entry::Vacant(e) => e.insert(Known::default()),
        };
        if let Some(n) = name {
            k.name = Some(n.to_string());
        }
        k.monster = monster.or(k.monster);
        k.model = model.or(k.model);
        let placed = of.position.flag(f);
        let at = |c: &Field| if placed { c.float(f) } else { None };
        out.emit(
            "entity_changes",
            Some(p),
            row! {
                entity_id: uid,
                act_index: of.act_index.int(f),
                zone_id: world.zone,
                name: k.name.clone(),
                monster: k.monster,
                model_id: k.model,
                x: at(&of.x),
                y: at(&of.y),
                z: at(&of.z),
            },
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MapFields, PLAYER, drive};

    #[test]
    fn a_row_per_first_sighting_and_change() {
        let uid = 0x0100_0000 | (0x0A3 << 12) | 1;
        let u = |id: i64| MapFields::new().int("UniqueNo", id).int("ActIndex", 1);
        let steps = vec![
            (0x00E, u(uid).text("Data.name", "Goblin").int("SubKind", 0).int("Data.model_id", 7)),
            (0x00E, u(uid).int("SendFlg.General", 1).int("Flags1.MonsterFlag", 1)),
            (0x00E, u(uid).int("SendFlg.Position", 1).float("x", 1.5).float("y", 2.0).float("z", 0.0)), // moves: no row
            (0x00E, u(uid).text("Data.name", "Goblin").int("SubKind", 0).int("Data.model_id", 8)),      // a new model
            (0x00E, u(uid).int("SubKind", 1)), // a humanoid look sends no model: no row
            (0x00E, u(99).text("Data.name", "Bee")), // another entity, at the same index
            (0x00E, u(uid).text("Data.name", "GoblinThug").int("SendFlg.Position", 1).float("x", 1.5)),
            (0x00E, u(uid)), // the name the world keeps for the index: no row
            (0x00D, MapFields::new().int("UniqueNo", PLAYER).text("name", "Kupipi")),
            (0x00D, MapFields::new().int("UniqueNo", PLAYER).text("name", "Kupipi")),
        ];
        let out = drive(&mut EntityChanges::default(), steps, Drive::default());
        let r = out.rows("entity_changes");
        let got: Vec<_> = (0..r.len())
            .map(|i| ["entity_id", "idx", "name", "model_id", "monster", "x", "y"].map(|c| r.get(i, c)))
            .collect();
        let (n, s, b, x) = (V::Int, |t: &str| V::Str(t.into()), V::Bool, V::Float);
        assert_eq!(
            got,
            [
                [n(uid), n(0), s("Goblin"), n(7), V::Null, V::Null, V::Null],
                [n(uid), n(1), s("Goblin"), n(7), b(true), V::Null, V::Null],
                [n(uid), n(3), s("Goblin"), n(8), b(true), V::Null, V::Null],
                [n(99), n(5), s("Bee"), V::Null, V::Null, V::Null, V::Null],
                [n(uid), n(6), s("GoblinThug"), n(8), b(true), x(1.5), V::Null],
                [n(PLAYER), n(8), s("Kupipi"), V::Null, V::Null, V::Null, V::Null],
            ]
        );
    }
}
