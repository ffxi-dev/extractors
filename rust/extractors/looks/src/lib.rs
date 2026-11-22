//! world/looks.py: how each entity looks and moves, as its updates (0x00E) say: one row per entity and state
//! in a zone visit, with how many updates came in it. Its Python twin keeps the docs.

use std::collections::HashMap;

use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

pub static META: Meta = Meta {
    name: "looks",
    version: 1,
    reads: &[(S2C, 0x00E), (S2C, 0x00A)],
    sparse: false,
    tables: &[Table {
        name: "entity_looks",
        columns: &[
            ("entity_id", I64),
            ("zone_id", I32),
            ("speed", I32),
            ("speed_base", I32),
            ("animation", I32),
            ("flags", ListStr),
            ("sub_kind", I32),
            ("status", I32),
            ("model_id", I32),
            ("look", ListI32),
            ("updates", I64),
        ],
    }],
};

/// A field of 0x00E, found once.
const fn on(path: &'static str) -> Field {
    Field::new(S2C, 0x00E, path)
}

macro_rules! fields {
    ($($path:literal),* $(,)?) => { [$(on($path)),*] };
}

static UID: Field = on("UniqueNo");
static DESPAWN: Field = on("SendFlg.Despawn");
static POSITION: Field = on("SendFlg.Position");
static GENERAL_SENT: Field = on("SendFlg.General");
static MODEL_SENT: Field = on("SendFlg.Model");
static NAME_SENT: Field = on("SendFlg.Name");
static SPEED: Field = on("Speed");
static SPEED_BASE: Field = on("SpeedBase");
static ANIMATION: Field = on("server_status");
static SUB_KIND: Field = on("SubKind");
static STATUS: Field = on("Status");
static MODEL_ID: Field = on("Data.model_id");
/// Flags0's flags, which come with a position, but MovTime and facetarget, which change with every step.
static MOVING: [Field; 4] = fields!("Flags0.RunMode", "Flags0.unknown_1_6", "Flags0.GroundFlag", "Flags0.KingFlag");
/// Flags1 to 3's, which come with SendFlg.General, by atom0s's names in XiPackets (unknown_* are his too).
#[rustfmt::skip]
static GENERAL: [Field; 61] = fields!(
    "Flags1.MonsterFlag", "Flags1.HideFlag", "Flags1.SleepFlag", "Flags1.unknown_0_3", "Flags1.unknown_0_4",
    "Flags1.ChocoboIndex", "Flags1.CliPosInitFlag", "Flags1.GraphSize", "Flags1.LfgFlag",
    "Flags1.AnonymousFlag", "Flags1.YellFlag", "Flags1.AwayFlag", "Flags1.Gender", "Flags1.PlayOnelineFlag",
    "Flags1.LinkShellFlag", "Flags1.LinkDeadFlag", "Flags1.TargetOffFlag", "Flags1.TalkUcoffFlag",
    "Flags1.unknown_2_5", "Flags1.unknown_2_6", "Flags1.unknown_2_7", "Flags1.GmLevel", "Flags1.HackMove",
    "Flags1.unknown_3_4", "Flags1.InvisFlag", "Flags1.TurnFlag", "Flags1.BazaarFlag", "Flags2.r", "Flags2.g",
    "Flags2.b", "Flags2.PvPFlag", "Flags2.ShadowFlag", "Flags2.ShipStartMode", "Flags2.CharmFlag",
    "Flags2.GmIconFlag", "Flags2.NamedFlag", "Flags2.SingleFlag", "Flags2.AutoPartyFlag", "Flags3.TrustFlag",
    "Flags3.LfgMasterFlag", "Flags3.PetNewFlag", "Flags3.unknown_0_3", "Flags3.MotStopFlag",
    "Flags3.CliPriorityFlag", "Flags3.PetFlag", "Flags3.OcclusionoffFlag", "Flags3.BallistaTeam",
    "Flags3.MonStat", "Flags3.unknown_2_3", "Flags3.unknown_2_4", "Flags3.SilenceFlag", "Flags3.unknown_2_6",
    "Flags3.NewCharacterFlag", "Flags3.MentorFlag", "Flags3.unknown_3_1", "Flags3.unknown_3_2",
    "Flags3.unknown_3_3", "Flags3.unknown_3_4", "Flags3.unknown_3_5", "Flags3.unknown_3_6", "Flags3.unknown_3_7"
);
#[rustfmt::skip]
static GRAP: [Field; 9] = fields!(
    "Data.GrapIDTbl[0]", "Data.GrapIDTbl[1]", "Data.GrapIDTbl[2]", "Data.GrapIDTbl[3]", "Data.GrapIDTbl[4]",
    "Data.GrapIDTbl[5]", "Data.GrapIDTbl[6]", "Data.GrapIDTbl[7]", "Data.GrapIDTbl[8]"
);
/// SubKinds whose Data is a look (GrapIDTbl) rather than a model.
const HUMANOID: [i64; 2] = [1, 7];

type Look = [Option<i64>; 9];

/// What an entity's updates last said. A flag is its value, 0 when unset: Python's tuple of the set ones.
/// The general flags are an index into Looks.sets, which keeps each set seen once.
#[derive(Clone, Copy, Default, Hash, PartialEq, Eq)]
struct State {
    speed: Option<i64>,
    speed_base: Option<i64>,
    animation: Option<i64>,
    flags0: [i64; 4],
    flags: u32,
    sub_kind: Option<i64>,
    status: Option<i64>,
    model_id: Option<i64>,
    look: Option<Look>,
}

fn read<const N: usize>(f: &Decoded, flags: &[Field; N]) -> [i64; N] {
    std::array::from_fn(|i| flags[i].int(f).unwrap_or(0))
}

/// Each flag set, as name=value.
fn named<'a>(flags: &'a [Field], values: &'a [i64]) -> impl Iterator<Item = String> + 'a {
    flags.iter().zip(values).filter(|&(_, &v)| v != 0).map(|(k, v)| format!("{}={v}", k.path))
}

pub struct Looks {
    state: HashMap<i64, State>,
    /// (entity id, state) -> its row's index in rows.
    seen: HashMap<(i64, State), usize>,
    /// Each row, and the updates that came in its state.
    rows: Vec<(RowId, i64)>,
    /// Each set of general flags seen, by index, and the index of each; the first, none set.
    sets: Vec<[i64; 61]>,
    set_of: HashMap<[i64; 61], u32>,
}

impl Default for Looks {
    fn default() -> Self {
        Looks {
            state: HashMap::new(),
            seen: HashMap::new(),
            rows: Vec::new(),
            sets: vec![[0; 61]],
            set_of: HashMap::from([([0; 61], 0)]),
        }
    }
}

impl Extractor for Looks {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        if p.opcode == 0x00A {
            self.state.clear();
            self.seen.clear();
            return;
        }
        let Some(uid) = UID.int(f) else { return };
        if DESPAWN.flag(f) {
            return;
        }
        let s = self.state.entry(uid).or_default();
        if POSITION.flag(f) {
            (s.speed, s.speed_base) = (SPEED.int(f), SPEED_BASE.int(f));
            s.flags0 = read(f, &MOVING);
        }
        if GENERAL_SENT.flag(f) {
            s.animation = ANIMATION.int(f);
            let flags = read(f, &GENERAL);
            s.flags = match self.set_of.get(&flags) {
                Some(&i) => i,
                None => {
                    self.sets.push(flags);
                    self.set_of.insert(flags, self.sets.len() as u32 - 1);
                    self.sets.len() as u32 - 1
                }
            };
        }
        let model = MODEL_SENT.flag(f);
        if (model || NAME_SENT.flag(f))
            && let Some(kind) = SUB_KIND.int(f)
        {
            (s.sub_kind, s.status) = (Some(kind), STATUS.int(f));
            if HUMANOID.contains(&kind) {
                if model {
                    (s.look, s.model_id) = (Some(std::array::from_fn(|i| GRAP[i].int(f))), None);
                }
            } else if let Some(m) = MODEL_ID.int(f) {
                (s.model_id, s.look) = (Some(m), None);
            }
        }
        let s = *s;
        let i = *self.seen.entry((uid, s)).or_insert_with(|| {
            let mut flags: Vec<String> =
                named(&MOVING, &s.flags0).chain(named(&GENERAL, &self.sets[s.flags as usize])).collect();
            flags.sort();
            let flags: Vec<Option<String>> = flags.into_iter().map(Some).collect();
            let look = s.look.map(|l| l.to_vec());
            let row = out.emit(
                "entity_looks",
                Some(p),
                row! {
                    entity_id: uid,
                    zone_id: world.zone,
                    speed: s.speed,
                    speed_base: s.speed_base,
                    animation: s.animation,
                    flags: flags,
                    sub_kind: s.sub_kind,
                    status: s.status,
                    model_id: s.model_id,
                    look: look,
                },
            );
            self.rows.push((row, 0));
            self.rows.len() - 1
        });
        self.rows[i].1 += 1;
    }

    fn finish(&mut self, _world: &World, out: &mut Out) {
        for &(row, n) in &self.rows {
            out.set(row, "updates", n);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MOB, MapFields, drive};

    #[test]
    fn every_path_is_one_of_0x00e() {
        let l = xc_decode::layout(S2C, 0x00E, None).unwrap();
        let one = [&UID, &DESPAWN, &POSITION, &GENERAL_SENT, &MODEL_SENT, &NAME_SENT, &SPEED, &SPEED_BASE];
        let one = one.into_iter().chain([&ANIMATION, &SUB_KIND, &STATUS, &MODEL_ID]);
        for k in one.chain(&MOVING).chain(&GENERAL).chain(&GRAP) {
            assert!(l.field(k.path).is_some(), "{}", k.path);
        }
    }

    #[test]
    fn a_state_holds_the_speeds_flags_and_model_last_sent_and_counts_its_updates() {
        let pal = MOB + 1;
        let u = |uid: i64| MapFields::new().int("UniqueNo", uid);
        let walk = |f: MapFields, speed| f.int("SendFlg.Position", 1).int("Speed", speed).int("SpeedBase", 40);
        let general = |f: MapFields, status| {
            f.int("SendFlg.General", 1).int("server_status", status).int("Flags1.MonsterFlag", 1).int("Flags2.g", 12)
        };
        let mut look = u(pal).int("SendFlg.Model", 1).int("SubKind", 1).int("Status", 0);
        for (i, k) in GRAP.iter().enumerate() {
            look = look.int(k.path, i as i64);
        }
        let steps = vec![
            (0x00A, MapFields::new().int("ZoneNo", 0x0A3)),
            (
                0x00E,
                general(walk(u(MOB), 40), 0)
                    .int("SendFlg.Name", 1)
                    .int("SubKind", 0)
                    .int("Status", 0)
                    .int("Data.model_id", 291),
            ),
            (0x00E, walk(u(MOB), 40)), // the same state: no flags sent, the last kept
            (0x00E, general(walk(u(MOB), 100), 1)), // it runs at a target
            (0x00E, u(MOB).int("SendFlg.Despawn", 1)), // a despawn sends no state
            (0x00E, look),
        ];
        let out = drive(&mut Looks::default(), steps, Drive::default());
        let r = out.rows("entity_looks");
        let cols = ["entity_id", "speed", "speed_base", "animation", "flags", "model_id", "look", "updates"];
        let got: Vec<_> = (0..r.len()).map(|i| cols.map(|c| r.get(i, c))).collect();
        let n = V::Int;
        let flags = V::Strs(vec![Some("Flags1.MonsterFlag=1".into()), Some("Flags2.g=12".into())]);
        assert_eq!(
            got,
            [
                [n(MOB), n(40), n(40), n(0), flags.clone(), n(291), V::Null, n(2)],
                [n(MOB), n(100), n(40), n(1), flags, n(291), V::Null, n(1)],
                [
                    n(pal),
                    V::Null,
                    V::Null,
                    V::Null,
                    V::Strs(vec![]),
                    V::Null,
                    V::Ints((0..9).map(Some).collect()),
                    n(1)
                ],
            ]
        );
    }
}
