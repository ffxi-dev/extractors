//! world/influence.py, line for line: the Campaign map (0x071 mode 2) and Adoulin's colonization map
//! (mode 3). Its Python twin keeps the docs.

use std::sync::LazyLock;

use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

/// Campaign areas in packet order, as zone ids: LSB's sql/campaign_map.sql.
const CAMPAIGN_ZONES: [i64; 26] =
    [80, 81, 82, 83, 84, 85, 175, 87, 88, 89, 90, 91, 92, 171, 94, 95, 96, 97, 98, 99, 164, 136, 137, 138, 155, 156];
/// Colonization areas in packet order, with their zone ids.
const COLONIES: [(&str, i64); 8] = [
    ("YahseHuntingGrounds", 260),
    ("CeizakBattlegrounds", 261),
    ("ForetDeHennetiel", 262),
    ("YorciaWeald", 263),
    ("MorimarBasaltFields", 265),
    ("MarjamiRavine", 266),
    ("KamihrDrifts", 267),
    ("RaKaznar", 274),
];

/// The campaign row's paths, in its columns' order.
const CAMPAIGN: [&str; 25] = [
    "data.ControlledAreas.Sandoria",
    "data.ControlledAreas.Bastok",
    "data.ControlledAreas.Windurst",
    "data.ControlledAreas.Beastman",
    "data.Nations.Sandoria.Morale",
    "data.Nations.Sandoria.Prosperity",
    "data.Nations.Sandoria.Reconnaissance",
    "data.Nations.Bastok.Morale",
    "data.Nations.Bastok.Prosperity",
    "data.Nations.Bastok.Reconnaissance",
    "data.Nations.Windurst.Morale",
    "data.Nations.Windurst.Prosperity",
    "data.Nations.Windurst.Reconnaissance",
    "data.Nations.BeastmanOrc.Morale",
    "data.Nations.BeastmanOrc.Prosperity",
    "data.Nations.BeastmanOrc.Reconnaissance",
    "data.Nations.BeastmanQuadav.Morale",
    "data.Nations.BeastmanQuadav.Prosperity",
    "data.Nations.BeastmanQuadav.Reconnaissance",
    "data.Nations.BeastmanYagudo.Morale",
    "data.Nations.BeastmanYagudo.Prosperity",
    "data.Nations.BeastmanYagudo.Reconnaissance",
    "data.Nations.BeastmanDarkKindred.Morale",
    "data.Nations.BeastmanDarkKindred.Prosperity",
    "data.Nations.BeastmanDarkKindred.Reconnaissance",
];
const AREA: [&str; 11] = [
    "Owner",
    "CurrentFortifications",
    "MaxFortifications",
    "CurrentResources",
    "MaxResources",
    "Heroism",
    "InfluenceSandoria",
    "InfluenceBastok",
    "InfluenceWindurst",
    "InfluenceBeastman",
    "unused00",
];

fn field(path: String) -> Field {
    Field::new(S2C, 0x071, path.leak())
}

static MODE: Field = Field::new(S2C, 0x071, "Mode");
static OFFSET: Field = Field::new(S2C, 0x071, "data.ZoneOffset");
static CAMPAIGNS: LazyLock<[Field; 25]> = LazyLock::new(|| CAMPAIGN.map(|k| field(k.to_string())));
static AREAS: LazyLock<Vec<[Field; 11]>> =
    LazyLock::new(|| (0..13).map(|i| AREA.map(|k| field(format!("data.Zones[{i}].{k}")))).collect());
static COLONY: LazyLock<Vec<[Field; 3]>> = LazyLock::new(|| {
    COLONIES
        .iter()
        .map(|(n, _)| {
            ["ColonizationRate", "CurrentBivouacs", "MaxBivouacs"].map(|k| field(format!("data.Zones.{n}.{k}")))
        })
        .collect()
});

pub static META: Meta = Meta {
    name: "influence",
    version: 1,
    reads: &[(S2C, 0x071)],
    sparse: true,
    tables: &[
        Table {
            name: "campaign",
            columns: &[
                ("sandoria_areas", I32),
                ("bastok_areas", I32),
                ("windurst_areas", I32),
                ("beastmen_areas", I32),
                ("sandoria_morale", I32),
                ("sandoria_prosperity", I32),
                ("sandoria_reconnaissance", I32),
                ("bastok_morale", I32),
                ("bastok_prosperity", I32),
                ("bastok_reconnaissance", I32),
                ("windurst_morale", I32),
                ("windurst_prosperity", I32),
                ("windurst_reconnaissance", I32),
                ("orcs_morale", I32),
                ("orcs_prosperity", I32),
                ("orcs_reconnaissance", I32),
                ("quadav_morale", I32),
                ("quadav_prosperity", I32),
                ("quadav_reconnaissance", I32),
                ("yagudo_morale", I32),
                ("yagudo_prosperity", I32),
                ("yagudo_reconnaissance", I32),
                ("kindred_morale", I32),
                ("kindred_prosperity", I32),
                ("kindred_reconnaissance", I32),
                ("zone_id", I32),
            ],
        },
        Table {
            name: "campaign_areas",
            columns: &[
                ("area", I32),
                ("area_zone_id", I32),
                ("owner", I32),
                ("fortifications", I32),
                ("max_fortifications", I32),
                ("resources", I32),
                ("max_resources", I32),
                ("heroism", I32),
                ("influence_sandoria", I32),
                ("influence_bastok", I32),
                ("influence_windurst", I32),
                ("influence_beastmen", I32),
                ("flag", I32),
                ("zone_id", I32),
            ],
        },
        Table {
            name: "colonization",
            columns: &[
                ("area_zone_id", I32),
                ("rate", I32),
                ("bivouacs", I32),
                ("max_bivouacs", I32),
                ("zone_id", I32),
            ],
        },
    ],
};

#[derive(Default)]
pub struct Influence;

impl Extractor for Influence {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        match MODE.int(f) {
            Some(2) => {
                let Some(offset) = OFFSET.int(f) else { return };
                if offset == 0 {
                    let id = out.emit("campaign", Some(p), row! { zone_id: world.zone });
                    // CAMPAIGN is in the table's column order; zone_id, last, has no path.
                    for (&(name, _), path) in META.tables[0].columns.iter().zip(CAMPAIGNS.iter()) {
                        out.set(id, name, path.int(f));
                    }
                }
                for (i, z) in AREAS.iter().enumerate() {
                    let area = offset + i as i64;
                    let Some(&zone) = usize::try_from(area).ok().and_then(|a| CAMPAIGN_ZONES.get(a)) else { break };
                    let v = |k: usize| z[k].int(f);
                    out.emit(
                        "campaign_areas",
                        Some(p),
                        row! {
                            area: area,
                            area_zone_id: zone,
                            owner: v(0),
                            fortifications: v(1),
                            max_fortifications: v(2),
                            resources: v(3),
                            max_resources: v(4),
                            heroism: v(5),
                            influence_sandoria: v(6),
                            influence_bastok: v(7),
                            influence_windurst: v(8),
                            influence_beastmen: v(9),
                            flag: v(10),
                            zone_id: world.zone,
                        },
                    );
                }
            }
            Some(3) => {
                for (&(_, zone), z) in COLONIES.iter().zip(COLONY.iter()) {
                    let Some(rate) = z[0].int(f) else { return };
                    out.emit(
                        "colonization",
                        Some(p),
                        row! {
                            area_zone_id: zone,
                            rate: rate,
                            bivouacs: z[1].int(f),
                            max_bivouacs: z[2].int(f),
                            zone_id: world.zone,
                        },
                    );
                }
            }
            _ => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MapFields, drive};

    fn campaign_map(offset: i64, owner: i64) -> (u16, MapFields) {
        let mut d = MapFields::new()
            .int("Mode", 2)
            .int("data.ZoneOffset", offset)
            .int("data.ControlledAreas.Sandoria", 9)
            .int("data.ControlledAreas.Beastman", 5)
            .int("data.Nations.BeastmanQuadav.Morale", 95);
        for i in 0..13 {
            d = d.int(&format!("data.Zones[{i}].Owner"), owner).int(&format!("data.Zones[{i}].Heroism"), 200);
        }
        (0x071, d)
    }

    #[test]
    fn a_campaign_map_in_two_packets() {
        let out = drive(&mut Influence, vec![campaign_map(0, 1), campaign_map(13, 7)], Drive::default());
        let c = out.rows("campaign");
        assert_eq!(c.len(), 1);
        let got = ["sandoria_areas", "beastmen_areas", "quadav_morale", "bastok_areas"].map(|k| c.get(0, k));
        assert_eq!(got, [V::Int(9), V::Int(5), V::Int(95), V::Null]);
        let a = out.rows("campaign_areas");
        assert_eq!(a.len(), 26);
        assert_eq!((a.get(0, "area_zone_id"), a.get(0, "owner")), (V::Int(80), V::Int(1))); // Southern San d'Oria [S]
        // Throne Room [S]
        assert_eq!(
            [a.get(25, "area"), a.get(25, "area_zone_id"), a.get(25, "owner")],
            [V::Int(25), V::Int(156), V::Int(7)]
        );
    }

    #[test]
    fn a_colonization_map() {
        let mut d = MapFields::new().int("Mode", 3);
        for (name, _) in COLONIES {
            for (k, v) in [("ColonizationRate", 80), ("CurrentBivouacs", 3), ("MaxBivouacs", 3)] {
                d = d.int(&format!("data.Zones.{name}.{k}"), v);
            }
        }
        let out = drive(&mut Influence, vec![(0x071, d)], Drive::default());
        let r = out.rows("colonization");
        let zones: Vec<_> = (0..r.len()).map(|i| r.get(i, "area_zone_id")).collect();
        assert_eq!(zones, [260, 261, 262, 263, 265, 266, 267, 274].map(V::Int));
        assert!(
            (0..r.len()).all(
                |i| ["rate", "bivouacs", "max_bivouacs"].map(|k| r.get(i, k)) == [V::Int(80), V::Int(3), V::Int(3)]
            )
        );
    }
}
