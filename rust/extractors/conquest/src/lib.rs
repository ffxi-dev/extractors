//! world/conquest.py, line for line: the conquest and Besieged map (0x05E), its nations, regions, and
//! beastman strongholds. Its Python twin keeps the docs.

use std::sync::LazyLock;

use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

const STRONGHOLDS: [&str; 3] = ["Mamook", "Halvung", "Arrapago"];
/// Who holds the Astral Candescence, by AstralCandescence.
const CANDESCENCE: [&str; 4] = ["Al Zahbi", "Mamook", "Halvung", "Arrapago"];

fn field(path: String) -> Field {
    Field::new(S2C, 0x05E, path.leak())
}

/// The conquest row's fields after the ranks, in its columns' order.
const NATION: [&str; 9] = [
    "Conquest.Alliance",
    "Conquest.NextTally",
    "Conquest.CurrentRegionSandoria",
    "Conquest.CurrentRegionBastok",
    "Conquest.CurrentRegionWindurst",
    "Conquest.CurrentRegionBeastmen",
    "Conquest.CurrentRegionSandoriaPct",
    "Conquest.CurrentRegionBastokPct",
    "Conquest.CurrentRegionWindurstPct",
];
static BALANCE: Field = Field::new(S2C, 0x05E, "Conquest.Balance");
static HELD: Field = Field::new(S2C, 0x05E, "Besieged.Overview.AstralCandescence");
static AL_ZAHBI: Field = Field::new(S2C, 0x05E, "Besieged.Overview.AlZahbiOrders");
static NATIONS: LazyLock<[Field; 9]> = LazyLock::new(|| NATION.map(|k| field(k.to_string())));
/// Each region's Owner, InfluenceRankingWithBeastmen, InfluenceRankingNoBeastmen, InfluenceGraphics.
static REGIONS: LazyLock<Vec<[Field; 4]>> = LazyLock::new(|| {
    (0..27)
        .map(|i| {
            ["Owner", "InfluenceRankingWithBeastmen", "InfluenceRankingNoBeastmen", "InfluenceGraphics"]
                .map(|k| field(format!("Conquest.Regions[{i}].{k}")))
        })
        .collect()
});
/// Each stronghold's Orders, Forces, Level, Mirrors, Prisoners, Unknown, then the overview's Orders and Level.
static FORTS: LazyLock<Vec<[Field; 8]>> = LazyLock::new(|| {
    STRONGHOLDS
        .iter()
        .map(|n| {
            let s = |k: &str| field(format!("Besieged.{n}Stronghold.{k}"));
            [
                s("Orders"),
                s("Forces"),
                s("Level"),
                s("Mirrors"),
                s("Prisoners"),
                s("Unknown"),
                field(format!("Besieged.Overview.{n}Orders")),
                field(format!("Besieged.Overview.{n}Level")),
            ]
        })
        .collect()
});

pub static META: Meta = Meta {
    name: "conquest",
    version: 2,
    reads: &[(S2C, 0x05E)],
    sparse: true,
    tables: &[
        Table {
            name: "conquest",
            columns: &[
                ("zone_id", I32),
                ("sandoria_rank", I32),
                ("bastok_rank", I32),
                ("windurst_rank", I32),
                ("alliance", I32),
                ("next_tally", I32),
                ("sandoria", I32),
                ("bastok", I32),
                ("windurst", I32),
                ("beastmen", I32),
                ("sandoria_no_beastmen", I32),
                ("bastok_no_beastmen", I32),
                ("windurst_no_beastmen", I32),
            ],
        },
        Table {
            name: "conquest_regions",
            columns: &[
                ("region_id", I32),
                ("owner", I32),
                ("ranking", I32),
                ("ranking_no_beastmen", I32),
                ("graphics", I32),
            ],
        },
        Table {
            name: "besieged",
            columns: &[
                ("stronghold", Str),
                ("orders", I32),
                ("forces", I32),
                ("level", I32),
                ("mirrors", I32),
                ("prisoners", I32),
                ("flag", I32),
                ("map_orders", I32),
                ("map_level", I32),
                ("candescence", Str),
                ("al_zahbi_orders", I32),
                ("zone_id", I32),
            ],
        },
    ],
};

#[derive(Default)]
pub struct Conquest;

impl Extractor for Conquest {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        // An older layout, or a stubbed packet.
        let Some(balance) = BALANCE.int(f) else { return };
        let [alliance, next_tally, sandoria, bastok, windurst, beastmen, sandoria_pct, bastok_pct, windurst_pct] =
            NATIONS.each_ref().map(|x| x.int(f));
        out.emit(
            "conquest",
            Some(p),
            row! {
                zone_id: world.zone,
                sandoria_rank: balance & 3,
                bastok_rank: (balance >> 2) & 3,
                windurst_rank: (balance >> 4) & 3,
                alliance: alliance,
                next_tally: next_tally,
                sandoria: sandoria,
                bastok: bastok,
                windurst: windurst,
                beastmen: beastmen,
                sandoria_no_beastmen: sandoria_pct,
                bastok_no_beastmen: bastok_pct,
                windurst_no_beastmen: windurst_pct,
            },
        );
        for (i, r) in REGIONS.iter().enumerate() {
            let [owner, ranking, no_beastmen, graphics] = r.each_ref().map(|x| x.int(f));
            if [owner, ranking, no_beastmen, graphics].iter().any(|v| v.is_some_and(|v| v != 0)) {
                out.emit(
                    "conquest_regions",
                    Some(p),
                    row! { region_id: i, owner: owner, ranking: ranking, ranking_no_beastmen: no_beastmen, graphics: graphics },
                );
            }
        }
        let held = HELD.int(f);
        let candescence = held.and_then(|h| CANDESCENCE.get(usize::try_from(h).ok()?)).copied();
        let al_zahbi = AL_ZAHBI.int(f);
        for (name, s) in STRONGHOLDS.iter().zip(FORTS.iter()) {
            let v = |i: usize| s[i].int(f);
            out.emit(
                "besieged",
                Some(p),
                row! {
                    stronghold: *name,
                    orders: v(0),
                    forces: v(1),
                    level: v(2),
                    mirrors: v(3),
                    prisoners: v(4),
                    flag: v(5),
                    map_orders: v(6),
                    map_level: v(7),
                    candescence: candescence,
                    al_zahbi_orders: al_zahbi,
                    zone_id: world.zone,
                },
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MapFields, drive};

    /// A 0x05E: region owners by index, the nations' Balance, and Mamook's orders, forces, and level.
    fn conquest_map(
        owners: &[i64],
        balance: i64,
        candescence: i64,
        al_zahbi: i64,
        mamook: [i64; 3],
    ) -> (u16, MapFields) {
        let mut d = MapFields::new()
            .int("Conquest.Balance", balance)
            .int("Conquest.Alliance", 0)
            .int("Conquest.NextTally", 33)
            .int("Conquest.CurrentRegionSandoria", 16)
            .int("Conquest.CurrentRegionBeastmen", 38)
            .int("Besieged.Overview.AstralCandescence", candescence)
            .int("Besieged.Overview.AlZahbiOrders", al_zahbi);
        for i in 0..27 {
            let owned = i < owners.len();
            d = d
                .int(&format!("Conquest.Regions[{i}].Owner"), if owned { owners[i] } else { 0 })
                .int(&format!("Conquest.Regions[{i}].InfluenceRankingWithBeastmen"), if owned { 45 } else { 0 });
        }
        for name in STRONGHOLDS {
            let [orders, forces, level] = if name == "Mamook" { mamook } else { [0, 97, 0] };
            let s = format!("Besieged.{name}Stronghold.");
            for (k, v) in [
                ("Orders", orders),
                ("Forces", forces),
                ("Level", level),
                ("Mirrors", 8),
                ("Prisoners", 0),
                ("Unknown", 0),
            ] {
                d = d.int(&format!("{s}{k}"), v);
            }
        }
        (0x05E, d)
    }

    fn map(owners: &[i64]) -> (u16, MapFields) {
        conquest_map(owners, 26, 0, 2, [5, 145, 4])
    }

    #[test]
    fn a_conquest_map() {
        let out = drive(&mut Conquest, vec![map(&[1, 3, 4])], Drive::default());
        let c = out.rows("conquest");
        assert_eq!(c.len(), 1);
        // Balance 26 is 0b01_10_10: Windurst first, San d'Oria and Bastok second.
        let ranks = ["sandoria_rank", "bastok_rank", "windurst_rank", "next_tally"].map(|k| c.get(0, k));
        assert_eq!(ranks, [V::Int(2), V::Int(2), V::Int(1), V::Int(33)]);
        let r = out.rows("conquest_regions");
        let regions: Vec<_> = (0..r.len()).map(|i| (r.get(i, "region_id"), r.get(i, "owner"))).collect();
        assert_eq!(regions, [(V::Int(0), V::Int(1)), (V::Int(1), V::Int(3)), (V::Int(2), V::Int(4))]);
        let b = out.rows("besieged");
        let forts: Vec<_> =
            (0..b.len()).map(|i| ["stronghold", "orders", "level", "candescence"].map(|k| b.get(i, k))).collect();
        let fort = |n: &str, o, l| [n.into(), V::Int(o), V::Int(l), "Al Zahbi".into()];
        assert_eq!(forts, [fort("Mamook", 5, 4), fort("Halvung", 0, 0), fort("Arrapago", 0, 0)]);
    }

    #[test]
    fn the_astral_candescence_taken_then_recovered() {
        let taken = conquest_map(&[1], 26, 1, 3, [0, 0, 0]);
        let out = drive(&mut Conquest, vec![taken, map(&[1])], Drive::default());
        let b = out.rows("besieged");
        let got: Vec<_> = (0..b.len())
            .filter(|&i| b.get(i, "stronghold") == "Mamook".into())
            .map(|i| (b.get(i, "candescence"), b.get(i, "al_zahbi_orders")))
            .collect();
        assert_eq!(got, [("Mamook".into(), V::Int(3)), ("Al Zahbi".into(), V::Int(2))]);
    }

    #[test]
    fn an_unknown_holder_of_the_astral_candescence_is_none() {
        let out = drive(&mut Conquest, vec![conquest_map(&[1], 26, 7, 2, [5, 145, 4])], Drive::default());
        let b = out.rows("besieged");
        assert!((0..b.len()).all(|i| b.get(i, "candescence") == V::Null));
    }
}
