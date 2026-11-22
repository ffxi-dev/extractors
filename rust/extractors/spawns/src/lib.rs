//! world/spawns.py: captain's spawntrack, light mode: mob defeats (0x029), despawns (0x038 'kesu'), and
//! respawns in view (0x00E). Its Python twin keeps the docs.

use std::collections::HashMap;

use xc_core::combat;
use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::world::Pos;
use xc_core::{Decoded, Field, Packet, S2C, World, row};

pub static META: Meta = Meta {
    name: "spawns",
    version: 1,
    reads: &[(S2C, 0x00E), (S2C, 0x029), (S2C, 0x038), (S2C, 0x00A)],
    sparse: true,
    tables: &[Table {
        name: "spawns",
        columns: &[
            ("kind", Str),
            ("entity_id", I64),
            ("x", F32),
            ("y", F32),
            ("z", F32),
            ("since_defeat_ms", I64),
            ("since_despawn_ms", I64),
            ("zone_id", I32),
        ],
    }],
};

/// The despawn animation's name in 0x038.
pub const KESU: i64 = u32::from_le_bytes(*b"kesu") as i64;
/// spawntrack ignores updates sooner than this after the defeat.
const MIN_RESPAWN_MS: i64 = 20_000;

static UID: Field = Field::new(S2C, 0x00E, "UniqueNo");
static POSITION: Field = Field::new(S2C, 0x00E, "SendFlg.Position");
static X: Field = Field::new(S2C, 0x00E, "x");
static Y: Field = Field::new(S2C, 0x00E, "y");
static Z: Field = Field::new(S2C, 0x00E, "z");
static STATUS: Field = Field::new(S2C, 0x00E, "server_status");
static MESSAGE: Field = Field::new(S2C, 0x029, "MessageNum");
static DEFEATED: Field = Field::new(S2C, 0x029, "UniqueNoTar");
static IDENT: Field = Field::new(S2C, 0x038, "ident");
static CAST_ON: Field = Field::new(S2C, 0x038, "UniqueNoTar");

#[derive(Default)]
pub struct Spawns {
    /// Entity id -> last (x, y, z).
    pos: HashMap<Option<i64>, Pos>,
    /// Mob id -> its defeat's time, until it is seen alive.
    defeated: HashMap<Option<i64>, i64>,
    /// Mob id -> its despawn's time, after that defeat.
    despawned: HashMap<Option<i64>, i64>,
}

impl Spawns {
    #[allow(clippy::too_many_arguments)]
    fn row(
        &self,
        out: &mut Out,
        p: &Packet,
        world: &World,
        kind: &str,
        uid: Option<i64>,
        defeat: Option<i64>,
        despawn: Option<i64>,
    ) {
        let (x, y, z) = self.pos.get(&uid).copied().unwrap_or_default();
        out.emit(
            "spawns",
            Some(p),
            row! {
                kind: kind,
                entity_id: uid,
                x: x,
                y: y,
                z: z,
                since_defeat_ms: defeat.map(|d| p.ts_ms - d),
                since_despawn_ms: despawn.map(|d| p.ts_ms - d),
                zone_id: world.zone,
            },
        );
    }
}

impl Extractor for Spawns {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        match p.opcode {
            0x00A => {
                self.pos.clear();
                self.defeated.clear();
                self.despawned.clear();
            }
            0x00E => {
                let uid = UID.int(f);
                if !POSITION.flag(f) {
                    return;
                }
                self.pos.insert(uid, (X.float(f), Y.float(f), Z.float(f)));
                if let Some(&defeat) = self.defeated.get(&uid)
                    && STATUS.int(f) == Some(0)
                    && p.ts_ms >= defeat + MIN_RESPAWN_MS
                {
                    self.defeated.remove(&uid);
                    let despawn = self.despawned.remove(&uid);
                    self.row(out, p, world, "spawned", uid, Some(defeat), despawn);
                }
            }
            0x029 => {
                let uid = DEFEATED.int(f);
                let defeat = self.defeated.get(&uid);
                // A second defeat message for the same death is skipped; one later means it came back unseen.
                if combat::is_defeat(MESSAGE.int(f))
                    && combat::is_mob(uid)
                    && defeat.is_none_or(|&d| p.ts_ms >= d + MIN_RESPAWN_MS)
                {
                    self.defeated.insert(uid, p.ts_ms);
                    self.despawned.remove(&uid);
                    self.row(out, p, world, "defeated", uid, None, None);
                }
            }
            _ => {
                if IDENT.int(f) != Some(KESU) {
                    return;
                }
                let uid = CAST_ON.int(f);
                if let Some(&defeat) = self.defeated.get(&uid)
                    && !self.despawned.contains_key(&uid)
                {
                    self.despawned.insert(uid, p.ts_ms);
                    self.row(out, p, world, "despawned", uid, Some(defeat), None);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MOB, MapFields, drive};

    const S: i64 = 1000;

    fn update(x: f64, y: f64, status: i64) -> (u16, MapFields) {
        let f = MapFields::new().int("UniqueNo", MOB).int("ActIndex", MOB & 0xFFF).int("SendFlg.Position", 1);
        (0x00E, f.float("x", x).float("y", y).float("z", 0.0).int("dir", 0).int("server_status", status))
    }

    #[test]
    fn a_mob_defeated_and_back() {
        let steps = vec![
            update(10.0, 20.0, 0),
            (0x029, MapFields::new().int("UniqueNoTar", MOB).int("MessageNum", 6)),
            (0x029, MapFields::new().int("UniqueNoTar", MOB).int("MessageNum", 20)), // the same death again
            (0x038, MapFields::new().int("UniqueNoTar", MOB).int("ident", KESU)),
            update(10.0, 20.0, 3), // still dead
            update(50.0, 60.0, 0),
        ];
        let times = Some(vec![0, S, 2 * S, 9 * S, 10 * S, 300 * S]);
        let out = drive(&mut Spawns::default(), steps, Drive { times, ..Drive::default() });
        let r = out.rows("spawns");
        let got: Vec<_> =
            (0..r.len()).map(|i| ["kind", "x", "since_defeat_ms", "since_despawn_ms"].map(|c| r.get(i, c))).collect();
        let (s, x, n) = (|t: &str| V::Str(t.into()), V::Float, V::Int);
        assert_eq!(
            got,
            [
                [s("defeated"), x(10.0), V::Null, V::Null],
                [s("despawned"), x(10.0), n(8 * S), V::Null],
                [s("spawned"), x(50.0), n(299 * S), n(291 * S)],
            ]
        );
    }
}
