//! items/synths.py, line for line: each synthesis result the zone sent, the character's own (0x06F) with its
//! recipe, and others' nearby (0x070), with the character's craft skills from its skills updates (0x062) and
//! skill-up messages (0x029). Its Python twin keeps the docs.

use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{Decoded, Field, Fields, Packet, S2C, World, row};

/// The Results retail's captures show the meaning of; a failure, whatever its Result, has grade -1.
fn outcome(result: i64) -> Option<&'static str> {
    match result {
        0 => Some("success"),
        12 => Some("desynth"),
        _ => None,
    }
}

macro_rules! fields {
    ($op:expr; $($path:literal),*) => { [$(Field::new(S2C, $op, $path)),*] };
}

/// Result, Grade, ItemNo, Count, then BreakNo[0..8]: of 0x06F, then of 0x070.
static SYNTH: [[Field; 12]; 2] = [
    fields!(0x06F; "Result", "Grade", "ItemNo", "Count", "BreakNo[0]", "BreakNo[1]", "BreakNo[2]", "BreakNo[3]",
            "BreakNo[4]", "BreakNo[5]", "BreakNo[6]", "BreakNo[7]"),
    fields!(0x070; "Result", "Grade", "ItemNo", "Count", "BreakNo[0]", "BreakNo[1]", "BreakNo[2]", "BreakNo[3]",
            "BreakNo[4]", "BreakNo[5]", "BreakNo[6]", "BreakNo[7]"),
];
static UP_KIND: [Field; 4] = fields!(0x06F; "UpKind[0]", "UpKind[1]", "UpKind[2]", "UpKind[3]");
static UP_LEVEL: [Field; 4] = fields!(0x06F; "UpLevel[0]", "UpLevel[1]", "UpLevel[2]", "UpLevel[3]");
static MATERIAL: [Field; 8] = fields!(0x06F; "MaterialNo[0]", "MaterialNo[1]", "MaterialNo[2]", "MaterialNo[3]",
    "MaterialNo[4]", "MaterialNo[5]", "MaterialNo[6]", "MaterialNo[7]");
/// skill_base[48] to [57]: fishing, then woodworking (49) to cooking (56), then synergy.
static CRAFT: [Field; 10] = fields!(0x062; "skill_base[48]", "skill_base[49]", "skill_base[50]", "skill_base[51]",
    "skill_base[52]", "skill_base[53]", "skill_base[54]", "skill_base[55]", "skill_base[56]", "skill_base[57]");
/// 0x029's MessageNum, Data (the skill), Data2 (the level).
static MESSAGE: [Field; 3] = fields!(0x029; "MessageNum", "Data", "Data2");
static CRYSTAL: Field = Field::new(S2C, 0x06F, "CrystalNo");
static NAME: Field = Field::new(S2C, 0x070, "name");

/// The fields' values that are there and not 0.
fn ids(f: &dyn Fields, fields: &[Field]) -> Vec<Option<i64>> {
    fields.iter().filter_map(|k| k.int(f).filter(|&v| v != 0)).map(Some).collect()
}

pub static META: Meta = Meta {
    name: "synths",
    version: 3,
    reads: &[(S2C, 0x06F), (S2C, 0x070), (S2C, 0x062), (S2C, 0x029)],
    sparse: true,
    tables: &[Table {
        name: "synths",
        columns: &[
            ("own", Bool),
            ("crafter", Str),
            ("result", I32),
            ("outcome", Str),
            ("grade", I32),
            ("item_id", I32),
            ("count", I32),
            ("crystal_id", I32),
            ("ingredients", ListI32),
            ("lost", ListI32),
            ("skill_kinds", ListI32),
            ("skill_levels", ListI32),
            ("skills", ListI32),
            ("zone_id", I32),
        ],
    }],
};

#[derive(Default)]
pub struct Synths {
    /// Each craft's level, skill 48 on, from the last 0x062: its bits 5 to 14 (0 to 4 are the rank, 15 the cap).
    crafts: [Option<i64>; 10],
    /// The level each craft reached (0x029, message 53) since the last synthesis: retail sends it, and the 0x062
    /// that shows it, before the result (0x06F) of the synthesis that raised it.
    reached: [Option<i64>; 10],
}

/// A craft's index in Synths' arrays: skill 48 is 0.
fn craft(skill: i64) -> Option<usize> {
    usize::try_from(skill - 48).ok().filter(|&i| i < 10)
}

impl Extractor for Synths {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        if p.opcode == 0x062 {
            for (c, k) in self.crafts.iter_mut().zip(&CRAFT) {
                *c = k.int(f).map(|v| (v & 0x7FFF) >> 5);
            }
            return;
        }
        if p.opcode == 0x029 {
            let [msg, skill, level] = MESSAGE.each_ref().map(|k| k.int(f));
            if let (Some(53), Some(c)) = (msg, skill.and_then(craft)) {
                self.reached[c] = level;
            }
            return;
        }
        let own = p.opcode == 0x06F;
        let k = &SYNTH[if own { 0 } else { 1 }];
        let result = k[0].int(f).unwrap_or(0);
        let grade = k[1].int(f);
        let failed = grade == Some(-1);
        let mut lost = if failed { ids(f, &k[4..]) } else { Vec::new() };
        let (mut ingredients, mut kinds, mut levels, mut skills) = (None, None, None, None);
        if own {
            let have = ids(f, &MATERIAL);
            lost.retain(|i| have.contains(i));
            ingredients = Some(have);
            let ups: Vec<(i64, i64)> = (0..4)
                .map(|i| (UP_KIND[i].int(f).unwrap_or(0), UP_LEVEL[i].int(f).unwrap_or(0)))
                .filter(|k| k.0 != 0)
                .collect();
            kinds = Some(ups.iter().map(|k| Some(k.0)).collect::<Vec<_>>());
            levels = Some(ups.iter().map(|k| Some(k.1)).collect::<Vec<_>>());
            // The level before this synthesis: one under the level it reached, else the last 0x062's.
            let before = |k: i64| craft(k).and_then(|c| self.reached[c].map(|n| n - 1).or(self.crafts[c]));
            skills = Some(ups.iter().map(|k| before(k.0)).collect::<Vec<_>>());
            self.reached = [None; 10];
        }
        out.emit(
            "synths",
            Some(p),
            row! {
                own: own,
                crafter: if own { world.character.clone() } else { NAME.text(f) },
                result: result,
                outcome: if failed { Some("failed") } else { outcome(result) },
                grade: grade,
                item_id: k[2].int(f).filter(|&v| v != 0),
                count: k[3].int(f),
                crystal_id: if own { CRYSTAL.int(f).filter(|&v| v != 0) } else { None },
                ingredients: ingredients,
                lost: lost,
                skill_kinds: kinds,
                skill_levels: levels,
                skills: skills,
                zone_id: world.zone,
            },
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MapFields, drive};

    fn fields(xs: &[(&str, i64)], name: Option<&str>) -> MapFields {
        let f = xs.iter().fold(MapFields::new(), |f, &(k, v)| f.int(k, v));
        if let Some(n) = name { f.text("name", n) } else { f }
    }

    fn ints(xs: &[i64]) -> V {
        V::Ints(xs.iter().map(|&x| Some(x)).collect())
    }

    #[test]
    fn the_characters_synthesis_and_someone_elses() {
        // Retail leaves BreakNo as an earlier synthesis set it: a success still names what that one lost, and a
        // failure may name an item that is no ingredient of this one.
        let own = fields(
            &[
                ("Result", 0),
                ("Grade", 1),
                ("Count", 1),
                ("ItemNo", 16465),
                ("UpKind[0]", 50),
                ("UpLevel[0]", 2),
                ("CrystalNo", 4096),
                ("MaterialNo[0]", 8819),
                ("BreakNo[0]", 1218),
            ],
            None,
        );
        let failed = fields(
            &[
                ("Result", 1),
                ("Grade", -1),
                ("ItemNo", 29695),
                ("BreakNo[0]", 8819),
                ("BreakNo[1]", 1223),
                ("CrystalNo", 4096),
                ("MaterialNo[0]", 8819),
            ],
            None,
        );
        let other = fields(&[("Result", 0), ("Count", 1), ("ItemNo", 16465), ("BreakNo[0]", 645)], Some("Nours"));
        // Retail's 14 (LSB's critical interruption) made an HQ2; its 10 failed.
        let lost = fields(&[("Result", 10), ("Grade", -1), ("ItemNo", 29695), ("BreakNo[0]", 645)], Some("Nours"));
        let made =
            fields(&[("Result", 14), ("Grade", 2), ("Count", 1), ("ItemNo", 745), ("BreakNo[0]", 645)], Some("Nours"));
        // Smithing 12, its rank 1, at its rank's cap (bit 15); goldsmithing, which this synthesis does not train, 30.
        let skills = MapFields::new().int("skill_base[50]", 0x8000 | (12 << 5) | 1).int("skill_base[51]", 30 << 5);
        // Retail tells of a skill-up that reaches a level, and sends the 0x062 that shows it, before the result: the
        // skill before it is one under. The next synthesis starts at the new level.
        let reached = MapFields::new().int("MessageNum", 53).int("Data", 50).int("Data2", 13);
        let raised = MapFields::new().int("skill_base[50]", 13 << 5);
        let again = fields(&[("Result", 0), ("Grade", 0), ("Count", 1), ("ItemNo", 16465), ("UpKind[0]", 50)], None);
        let steps = vec![
            (0x062, skills),
            (0x029, reached),
            (0x062, raised),
            (0x06F, own),
            (0x06F, again),
            (0x06F, failed),
            (0x070, other),
            (0x070, lost),
            (0x070, made),
        ];
        let out = drive(&mut Synths::default(), steps, Drive::default());
        let r = out.rows("synths");
        let keys = [
            "own",
            "crafter",
            "outcome",
            "grade",
            "item_id",
            "crystal_id",
            "ingredients",
            "lost",
            "skill_kinds",
            "skill_levels",
            "skills",
        ];
        let got: Vec<Vec<V>> = (0..r.len()).map(|i| keys.iter().map(|k| r.get(i, k)).collect()).collect();
        let (s, n, i) = (|x: &str| V::Str(x.into()), V::Null, V::Int);
        let (me, nours) = (s("Me"), s("Nours"));
        assert_eq!(
            got,
            [
                vec![
                    V::Bool(true),
                    me.clone(),
                    s("success"),
                    i(1),
                    i(16465),
                    i(4096),
                    ints(&[8819]),
                    ints(&[]),
                    ints(&[50]),
                    ints(&[2]),
                    ints(&[12])
                ],
                vec![
                    V::Bool(true),
                    s("Me"),
                    s("success"),
                    i(0),
                    i(16465),
                    n.clone(),
                    ints(&[]),
                    ints(&[]),
                    ints(&[50]),
                    ints(&[0]),
                    ints(&[13])
                ],
                vec![
                    V::Bool(true),
                    me,
                    s("failed"),
                    i(-1),
                    i(29695),
                    i(4096),
                    ints(&[8819]),
                    ints(&[8819]),
                    ints(&[]),
                    ints(&[]),
                    ints(&[])
                ],
                vec![
                    V::Bool(false),
                    nours.clone(),
                    s("success"),
                    n.clone(),
                    i(16465),
                    n.clone(),
                    n.clone(),
                    ints(&[]),
                    n.clone(),
                    n.clone(),
                    n.clone()
                ],
                vec![
                    V::Bool(false),
                    nours.clone(),
                    s("failed"),
                    i(-1),
                    i(29695),
                    n.clone(),
                    n.clone(),
                    ints(&[645]),
                    n.clone(),
                    n.clone(),
                    n.clone()
                ],
                vec![
                    V::Bool(false),
                    nours,
                    n.clone(),
                    i(2),
                    i(745),
                    n.clone(),
                    n.clone(),
                    ints(&[]),
                    n.clone(),
                    n.clone(),
                    n
                ],
            ]
        );
    }
}
