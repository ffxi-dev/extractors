//! items/fishing.py, line for line: each cast the character made, its minigame, and its outcome. Its Python
//! twin keeps the docs.

use std::collections::{HashMap, HashSet};

use xc_core::combat::is_mob;
use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::{C2S, Decoded, Field, Packet, S2C, World, row};
use xc_gathering::{Held, WINDOW_MS, place, place_columns};

/// c2s 0x01A's ActionID for a cast.
const CAST: i64 = 14;
/// 0x050's EquipKind: the range and ammo slots.
const ROD: i64 = 2;
const BAIT: i64 = 3;
/// The zone's fishing messages, from its own offset, as LSB's FISHMESSAGEOFFSET numbers them.
const NOTHING: i64 = 0x04;
const KEEN: i64 = 0x35;
const ONE: i64 = 0x27;
const MANY: i64 = 0x0E;
const GAVE_UP: i64 = 200;
/// A monster reeled in claims the character within this of the cast's end.
const MONSTER_MS: i64 = 10_000;

/// 0x037's server_status once a hooked fight ends.
fn outcome(status: Option<i64>) -> Option<&'static str> {
    match status? {
        58 => Some("caught"),
        59 => Some("rod break"),
        60 => Some("line break"),
        61 => Some("monster"),
        62 => Some("lost"),
        _ => None,
    }
}

const HOOK: [i64; 4] = [0x08, 0x32, 0x33, 0x34];

fn hook(m: i64) -> Option<&'static str> {
    match m {
        0x08 => Some("small fish"),
        0x32 => Some("large fish"),
        0x33 => Some("item"),
        0x34 => Some("monster"),
        _ => None,
    }
}

fn feeling(m: i64) -> Option<&'static str> {
    match m {
        0x29 => Some("good"),
        0x2A => Some("bad"),
        0x2B => Some("terrible"),
        0x2C => Some("no skill"),
        0x2D => Some("no skill sure"),
        0x2E => Some("no skill positive"),
        0x36 => Some("epic"),
        _ => None,
    }
}

static EQUIP: [Field; 3] = [
    Field::new(S2C, 0x050, "EquipKind"),
    Field::new(S2C, 0x050, "Category"),
    Field::new(S2C, 0x050, "PropertyItemIndex"),
];
static ACTION: Field = Field::new(C2S, 0x01A, "ActionID");
macro_rules! game {
    ($($g:literal),*) => { [$(Field::new(S2C, 0x115, $g)),*] };
}
/// 0x115's minigame fields, each a column of its name.
static GAME: [Field; 9] = game!(
    "stamina",
    "arrow_delay",
    "regen",
    "move_frequency",
    "arrow_damage",
    "arrow_regen",
    "time",
    "angler_sense",
    "intuition"
);
static MODE: [Field; 2] = [Field::new(C2S, 0x110, "mode"), Field::new(C2S, 0x110, "para")];
/// UniqueNo and MesNum of 0x036, 0x037, 0x02A, 0x027.
static UID: [Field; 4] = [
    Field::new(S2C, 0x036, "UniqueNo"),
    Field::new(S2C, 0x037, "UniqueNo"),
    Field::new(S2C, 0x02A, "UniqueNo"),
    Field::new(S2C, 0x027, "UniqueNo"),
];
static MES_036: Field = Field::new(S2C, 0x036, "MesNum");
static STATUS: Field = Field::new(S2C, 0x037, "server_status");
/// 0x00E's mob, whether it despawned, and its claim.
static MOB: [Field; 4] = [
    Field::new(S2C, 0x00E, "UniqueNo"),
    Field::new(S2C, 0x00E, "SendFlg.Despawn"),
    Field::new(S2C, 0x00E, "SendFlg.ClaimStatus"),
    Field::new(S2C, 0x00E, "BtTargetID"),
];
static SENSE: [Field; 2] = [Field::new(S2C, 0x02A, "MesNum"), Field::new(S2C, 0x02A, "num[0]")];
static CATCH: [Field; 3] =
    [Field::new(S2C, 0x027, "MesNum"), Field::new(S2C, 0x027, "Num1[0]"), Field::new(S2C, 0x027, "Num1[1]")];

fn uid(op: u16) -> &'static Field {
    match op {
        0x036 => &UID[0],
        0x037 => &UID[1],
        0x02A => &UID[2],
        _ => &UID[3],
    }
}

pub static META: Meta = Meta {
    name: "fishing",
    version: 5,
    reads: &[
        (S2C, 0x01E),
        (S2C, 0x01F),
        (S2C, 0x020),
        (S2C, 0x00A),
        (S2C, 0x00E),
        (C2S, 0x01A),
        (C2S, 0x110),
        (S2C, 0x115),
        (S2C, 0x027),
        (S2C, 0x02A),
        (S2C, 0x036),
        (S2C, 0x037),
        (S2C, 0x050),
    ],
    sparse: true,
    tables: &[Table {
        name: "fishing",
        columns: place_columns![
            ("rod_id", I32),
            ("bait_id", I32),
            ("hook_ms", I64),
            ("end_ms", I64),
            ("stamina", I32),
            ("arrow_delay", I32),
            ("regen", I32),
            ("move_frequency", I32),
            ("arrow_damage", I32),
            ("arrow_regen", I32),
            ("time", I32),
            ("angler_sense", I32),
            ("intuition", I32),
            ("hook", Str),
            ("feeling", Str),
            ("sensed_id", I32),
            ("reel", I32),
            ("outcome", Str),
            ("item_id", I32),
            ("count", I32),
            ("monster_id", I64),
            ("messages", ListI32),
        ],
    }],
};

/// 0x027's (MesNum, Num1[0], Num1[1], ts).
type Catch = (Option<i64>, Option<i64>, Option<i64>, i64);

/// A cast's row, and what finish() names it by.
struct Cast {
    id: RowId,
    zone: Option<i64>,
    hook_ms: Option<i64>,
    end_ms: Option<i64>,
    /// The first mob to claim the character since the bite.
    monster: Option<i64>,
    reel: Option<i64>,
    outcome: Option<&'static str>,
    messages: Vec<Option<i64>>,
    /// 0x02A's (MesNum, num[0]): the first after the bite.
    sense: Option<(Option<i64>, Option<i64>)>,
    /// 0x027's (MesNum, Num1[0], Num1[1], ts): the first after the bite.
    catch: Option<Catch>,
    /// (ts, item) the main inventory gained since the bite.
    gained: Vec<(i64, i64)>,
}

#[derive(Default)]
pub struct Fishing {
    held: Held,
    /// EquipKind -> (container, slot)
    equip: HashMap<Option<i64>, (Option<i64>, Option<i64>)>,
    /// The cast now, in casts.
    row: Option<usize>,
    casts: Vec<Cast>,
    /// Whether the cast's animation still runs: its messages are its own.
    casting: bool,
    /// Mob -> its last claimer, since it last despawned.
    claims: HashMap<i64, i64>,
}

impl Extractor for Fishing {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let key = p.key();
        if key == (S2C, 0x00A) {
            self.row = None;
            self.claims.clear();
            return;
        }
        if key == (S2C, 0x00E) {
            self.claim(p, f, world);
            return;
        }
        if Held::reads(key) {
            if let Some(item) = self.held.gained(p, f)
                && let Some(r) = self.row
                && self.casts[r].hook_ms.is_some()
            {
                self.casts[r].gained.push((p.ts_ms, item));
            }
            return;
        }
        match key {
            (S2C, 0x050) => {
                self.equip.insert(EQUIP[0].int(f), (EQUIP[1].int(f), EQUIP[2].int(f)));
                return;
            }
            (C2S, 0x01A) => {
                if ACTION.int(f) == Some(CAST) {
                    self.cast(p, world, out);
                }
                return;
            }
            (S2C, 0x115) => {
                let r = match self.row {
                    Some(r) if self.casts[r].hook_ms.is_none() => r,
                    _ => self.cast(p, world, out),
                };
                for g in &GAME {
                    out.set(self.casts[r].id, g.path, g.int(f));
                }
                out.set(self.casts[r].id, "hook_ms", p.ts_ms);
                self.casts[r].hook_ms = Some(p.ts_ms);
                return;
            }
            _ => {}
        }
        let me = world.character_id;
        let Some(r) = self.row else { return };
        if p.direction == S2C && me.is_some_and(|m| m != 0) && uid(p.opcode).int(f) != me {
            return;
        }
        let c = &mut self.casts[r];
        match key {
            (C2S, 0x110) => {
                if MODE[0].int(f) == Some(3) {
                    c.reel = MODE[1].int(f);
                    out.set(c.id, "reel", c.reel);
                }
            }
            (S2C, 0x036) => {
                if self.casting {
                    c.messages.push(MES_036.int(f));
                }
            }
            (S2C, 0x037) if outcome(STATUS.int(f)).is_some() => {
                // The animation ends the cast: a later message, such as a dig's, is not this cast's.
                self.casting = false;
                if c.hook_ms.is_some() && c.outcome.is_none() {
                    c.outcome = outcome(STATUS.int(f));
                    c.end_ms = Some(p.ts_ms);
                    out.set(c.id, "end_ms", p.ts_ms);
                }
            }
            _ if c.hook_ms.is_none() => {}
            (S2C, 0x02A) => {
                c.sense.get_or_insert((SENSE[0].int(f), SENSE[1].int(f)));
            }
            (S2C, 0x027) => {
                c.catch.get_or_insert((CATCH[0].int(f), CATCH[1].int(f), CATCH[2].int(f), p.ts_ms));
            }
            _ => {}
        }
    }

    /// Name what each cast's messages say, by the zone's offset: the one that explains the most of its casts.
    fn finish(&mut self, _world: &World, out: &mut Out) {
        let mut base: HashMap<Option<i64>, i64> = HashMap::new();
        let zones: HashSet<Option<i64>> = self.casts.iter().map(|c| c.zone).collect();
        for zone in zones {
            let casts: Vec<(bool, &[Option<i64>])> = self
                .casts
                .iter()
                .filter(|c| c.zone == zone)
                .map(|c| (c.hook_ms.is_some(), c.messages.as_slice()))
                .collect();
            let mut tried = HashSet::new();
            for &(bit, said) in &casts {
                if let Some(&Some(first)) = said.first() {
                    let hs: &[i64] = if bit { &HOOK } else { &[NOTHING] };
                    tried.extend(hs.iter().map(|h| first - h));
                }
            }
            let scored: Vec<(usize, i64)> =
                tried.into_iter().map(|at| (casts.iter().filter(|&&(b, s)| explains(at, b, s)).count(), at)).collect();
            let best = scored.iter().map(|s| s.0).max().unwrap_or(0);
            if best > 0 && scored.iter().filter(|s| s.0 == best).count() == 1 {
                base.insert(zone, scored.iter().find(|s| s.0 == best).unwrap().1);
            }
        }
        for c in &self.casts {
            out.set(c.id, "messages", c.messages.clone());
            if c.hook_ms.is_none() {
                out.set(c.id, "outcome", "nothing");
                continue;
            }
            let mut outcome = c.outcome;
            if outcome == Some("lost") && c.reel == Some(GAVE_UP) {
                outcome = Some("gave up");
            }
            out.set(c.id, "outcome", outcome);
            if outcome == Some("monster") {
                out.set(c.id, "monster_id", c.monster);
            }
            let at = base.get(&c.zone).copied();
            let off = |m: Option<i64>| Some(m? - at?);
            let said = || c.messages.iter().filter_map(|&m| off(m));
            let mut feel = said().find_map(feeling);
            let mut sensed = None;
            if let Some((mes, num)) = c.sense
                && off(mes) == Some(KEEN)
            {
                (feel, sensed) = (Some("keen"), num);
            }
            out.set(c.id, "hook", said().find_map(hook));
            out.set(c.id, "feeling", feel);
            out.set(c.id, "sensed_id", sensed);
            if let Some(catch) = c.catch
                && caught(at, catch, &c.gained)
            {
                out.set(c.id, "item_id", catch.1);
                out.set(c.id, "count", if off(catch.0) == Some(MANY) { catch.2 } else { Some(1) });
            }
        }
    }
}

impl Fishing {
    /// A mob's claim: the first mob to claim the character from the bite to MONSTER_MS after the cast's
    /// end is what it reeled in. A mob that had claimed it already is not.
    fn claim(&mut self, p: &Packet, f: &Decoded, world: &World) {
        let Some(uid) = MOB[0].int(f).filter(|&u| is_mob(Some(u))) else { return };
        if MOB[1].flag(f) {
            self.claims.remove(&uid);
            return;
        }
        let Some(by) = MOB[3].int(f).filter(|&c| c != 0 && MOB[2].flag(f)) else { return };
        let before = self.claims.insert(uid, by);
        if Some(by) != world.character_id || before == Some(by) {
            return;
        }
        if let Some(r) = self.row
            && let c = &mut self.casts[r]
            && c.hook_ms.is_some()
            && c.monster.is_none()
            && c.end_ms.is_none_or(|end| p.ts_ms <= end + MONSTER_MS)
        {
            c.monster = Some(uid);
        }
    }

    fn cast(&mut self, p: &Packet, world: &World, out: &mut Out) -> usize {
        // Index 0 empties a slot; (0, 0) is the gil.
        let held = |k| match self.equip.get(&Some(k)) {
            Some(&e) if e.1.is_some_and(|s| s != 0) => world.items.get(&e).copied().flatten(),
            _ => None,
        };
        // finish() writes messages, as every row's outcome.
        let id = out.emit("fishing", Some(p), row! { rod_id: held(ROD), bait_id: held(BAIT) });
        place(p, world, out, id);
        self.casts.push(Cast {
            id,
            zone: world.zone,
            hook_ms: None,
            end_ms: None,
            monster: None,
            reel: None,
            outcome: None,
            messages: Vec::new(),
            sense: None,
            catch: None,
            gained: Vec::new(),
        });
        self.casting = true;
        self.row = Some(self.casts.len() - 1);
        self.casts.len() - 1
    }
}

/// Whether offset at reads a cast's messages as LSB numbers them: 'nothing', or what bit and a feeling.
fn explains(at: i64, bit: bool, said: &[Option<i64>]) -> bool {
    let off = |i: usize| said.get(i).copied().flatten().map(|m| m - at);
    if said.is_empty() {
        return false;
    }
    if !bit {
        return said.len() == 1 && off(0) == Some(NOTHING);
    }
    off(0).and_then(hook).is_some() && (said.len() < 2 || off(1).and_then(feeling).is_some())
}

/// Whether a 0x027 names this cast's catch: the zone's catch message by its offset; with no offset, the item
/// the main inventory gained since the bite, up to 3 s after it.
fn caught(at: Option<i64>, catch: Catch, gained: &[(i64, i64)]) -> bool {
    let (message, item, _, ts) = catch;
    match at {
        Some(at) => message.is_some_and(|m| m - at == ONE || m - at == MANY),
        None => gained.iter().any(|&(t, g)| Some(g) == item && t <= ts + WINDOW_MS),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::extract::Rows;
    use xc_core::testing::{Drive, MOB, MapFields, PLAYER, STRANGER, drive};

    const ZONE: i64 = 111;
    const ROD_ID: i64 = 17386;
    const BAIT_ID: i64 = 17399;
    const ICEFISH: i64 = 4470;
    const GAVIAL: i64 = 4477;
    /// 'You didn't catch anything.' is BASE + 4.
    const BASE: i64 = 40018;
    const GAME_V: [i64; 9] = [4462, 5, 128, 11, 820, 410, 40, 0, 18];

    type Step = (u16, MapFields);

    fn said(n: i64) -> Step {
        (0x036, MapFields::new().int("UniqueNo", PLAYER).int("MesNum", BASE + n))
    }

    fn status(s: i64) -> Step {
        (0x037, MapFields::new().int("UniqueNo", PLAYER).int("server_status", s))
    }

    fn cast() -> Step {
        (0x01A, MapFields::new().int("ActionID", 14))
    }

    fn reel(para: i64) -> Step {
        (0x110, MapFields::new().int("mode", 3).int("para", para).int("para2", 0))
    }

    fn game(sense: i64) -> Step {
        let mut f = MapFields::new();
        for (g, v) in GAME.iter().zip(GAME_V) {
            f = f.int(g.path, if g.path == "angler_sense" { sense } else { v });
        }
        (0x115, f)
    }

    fn slot(index: i64, item: i64, n: i64) -> Step {
        (0x020, MapFields::new().int("Category", 0).int("ItemIndex", index).int("ItemNo", item).int("ItemNum", n))
    }

    fn equip(kind: i64, index: i64) -> Step {
        (0x050, MapFields::new().int("EquipKind", kind).int("Category", 0).int("PropertyItemIndex", index))
    }

    fn message(op: u16, mes: i64, a: (&str, i64), b: Option<i64>) -> Step {
        let f = MapFields::new().int("UniqueNo", PLAYER).int("MesNum", BASE + mes).int(a.0, a.1);
        (op, if let Some(b) = b { f.int("Num1[1]", b) } else { f })
    }

    /// A mob's update, claimed by one.
    fn claim(mob: i64, by: i64) -> Step {
        let f = MapFields::new().int("UniqueNo", mob).int("ActIndex", mob & 0xFFF);
        (0x00E, f.int("SendFlg.ClaimStatus", 1).int("BtTargetID", by))
    }

    fn catch(mes: i64, item: i64, n: i64) -> Step {
        message(0x027, mes, ("Num1[0]", item), Some(n))
    }

    /// A zone-in, the rod and bait equipped, then what follows.
    fn fish(after: Vec<Step>) -> Rows {
        let mut steps = vec![
            (
                0x00A,
                MapFields::new()
                    .int("ZoneNo", ZONE)
                    .int("WeatherNumber", 12)
                    .float("PosHead.x", 1.0)
                    .float("PosHead.y", 2.0)
                    .float("PosHead.z", 3.0),
            ),
            slot(26, ROD_ID, 1),
            slot(57, BAIT_ID, 12),
            equip(ROD, 26),
            equip(BAIT, 57),
        ];
        steps.extend(after);
        let directions = steps.iter().map(|(op, _)| if matches!(op, 0x01A | 0x110) { C2S } else { S2C }).collect();
        drive(&mut Fishing::default(), steps, Drive { directions: Some(directions), ..Drive::default() })
            .tables
            .remove(0)
    }

    fn s(x: &str) -> V {
        V::Str(x.into())
    }

    #[test]
    fn a_cast_with_the_bait_taken_off_has_no_bait() {
        let r = fish(vec![slot(0, 65535, 1000), equip(BAIT, 0), cast(), said(4), status(62)]);
        assert_eq!((r.len(), r.get(0, "rod_id"), r.get(0, "bait_id")), (1, V::Int(ROD_ID), V::Null));
    }

    #[test]
    fn a_message_after_the_cast_ended_is_not_its_own() {
        let r = fish(vec![cast(), said(4), status(62), said(0x2C), cast(), said(8), game(0), said(0x29)]);
        assert_eq!(r.get(0, "messages"), V::Ints(vec![Some(BASE + 4)]));
        assert_eq!((r.get(1, "hook"), r.get(1, "feeling")), (s("small fish"), s("good")));
    }

    #[test]
    fn a_cast_its_minigame_and_its_catch() {
        let r = fish(vec![
            cast(),
            said(4),
            status(62),
            cast(),
            said(8),
            game(0),
            said(0x2C),
            reel(0),
            status(58),
            catch(0x0E, ICEFISH, 3),
        ]);
        assert_eq!((r.get(0, "outcome"), r.get(0, "hook_ms"), r.get(0, "stamina")), (s("nothing"), V::Null, V::Null));
        let got: Vec<V> = ["zone_id", "rod_id", "bait_id", "weather_id"].iter().map(|c| r.get(1, c)).collect();
        assert_eq!(got, [ZONE, ROD_ID, BAIT_ID, 12].map(V::Int));
        assert_eq!(GAME.each_ref().map(|g| r.get(1, g.path)), GAME_V.map(V::Int));
        let got: Vec<V> =
            ["hook", "feeling", "reel", "outcome", "item_id", "count"].iter().map(|c| r.get(1, c)).collect();
        assert_eq!(got, [s("small fish"), s("no skill"), V::Int(0), s("caught"), V::Int(ICEFISH), V::Int(3)]);
        let (V::Int(hook), V::Int(end)) = (r.get(1, "hook_ms"), r.get(1, "end_ms")) else { panic!() };
        assert_eq!(end, hook + 3000);
    }

    #[test]
    fn an_item_given_up_a_line_break_and_a_keen_sense() {
        let r = fish(vec![
            cast(),
            said(4),
            status(62),
            cast(),
            said(0x33),
            game(0),
            said(0x29),
            reel(200),
            said(0x24),
            status(62),
            cast(),
            said(0x32),
            game(3),
            message(0x02A, 0x35, ("num[0]", GAVIAL), None),
            reel(0),
            said(6),
            status(60),
        ]);
        let got: Vec<Vec<V>> = (1..3)
            .map(|i| ["hook", "feeling", "sensed_id", "outcome", "item_id"].iter().map(|c| r.get(i, c)).collect())
            .collect();
        assert_eq!(
            got,
            [
                vec![s("item"), s("good"), V::Null, s("gave up"), V::Null],
                vec![s("large fish"), s("keen"), V::Int(GAVIAL), s("line break"), V::Null],
            ]
        );
    }

    #[test]
    fn a_cast_refused_for_want_of_bait_gives_no_offset() {
        let bite = || vec![cast(), said(8), game(0), said(0x29), reel(0), status(58), catch(0x27, ICEFISH, 6)];
        let r = fish([vec![cast(), said(2)], bite(), bite()].concat());
        let got: Vec<Vec<V>> =
            (0..3).map(|i| ["outcome", "hook", "feeling", "item_id"].iter().map(|c| r.get(i, c)).collect()).collect();
        assert_eq!(
            got,
            [
                vec![s("nothing"), V::Null, V::Null, V::Null],
                vec![s("caught"), s("small fish"), s("good"), V::Int(ICEFISH)],
                vec![s("caught"), s("small fish"), s("good"), V::Int(ICEFISH)],
            ]
        );
    }

    #[test]
    fn with_no_offset_a_catch_is_an_item_the_inventory_gained() {
        let bite = || vec![cast(), said(8), game(0), reel(0), status(58), catch(0x27, ICEFISH, 6)];
        let r = fish([bite(), vec![slot(40, ICEFISH, 1)], bite()].concat());
        let got: Vec<V> = ["hook", "outcome", "item_id", "count"].iter().map(|c| r.get(0, c)).collect();
        assert_eq!(got, [V::Null, s("caught"), V::Int(ICEFISH), V::Int(1)]);
        assert_eq!((r.get(1, "outcome"), r.get(1, "item_id")), (s("caught"), V::Null));
    }

    /// Retail spawns a monster reeled in beside the character, claimed by it, just before the animation
    /// (0x037 61): NZlAAFDTRYzV's Greater Pugil, 01003003, 0.4 s before.
    #[test]
    fn a_monster_reeled_in_is_the_mob_that_claims_the_character() {
        let other = MOB + 1;
        let bite = || vec![cast(), said(0x34), game(0), said(0x29), reel(0)];
        let r = fish(
            [
                vec![claim(other, PLAYER), cast(), said(4), status(62)],
                // a mob already fighting it, and another player's claim, are not the catch
                [bite(), vec![claim(other, PLAYER), claim(MOB + 2, STRANGER), claim(MOB, PLAYER), status(61)]].concat(),
                [bite(), vec![claim(MOB + 3, PLAYER), status(62)]].concat(),
                [bite(), vec![status(61)], vec![equip(ROD, 26); 10], vec![claim(MOB + 4, PLAYER)]].concat(),
            ]
            .concat(),
        );
        let got: Vec<(V, V)> = (1..4).map(|i| (r.get(i, "outcome"), r.get(i, "monster_id"))).collect();
        assert_eq!(got, [(s("monster"), V::Int(MOB)), (s("lost"), V::Null), (s("monster"), V::Null)],); // lost, it never spawns; one claiming 11 s after the end is another fight
    }

    #[test]
    fn a_quest_line_after_a_bite_is_no_catch() {
        let bite = || vec![cast(), said(8), game(0), said(0x29), reel(0), status(58), catch(0x59, 1182, 2)];
        let r = fish([bite(), bite()].concat());
        for i in 0..2 {
            let got: Vec<V> = ["hook", "outcome", "item_id"].iter().map(|c| r.get(i, c)).collect();
            assert_eq!(got, [s("small fish"), s("caught"), V::Null]);
        }
    }
}
