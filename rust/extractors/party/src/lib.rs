//! world/party.py, line for line: each member a party list names (0x0DD, 0x0E2) and each the alliance list
//! names (0x0C8). Its Python twin keeps the docs.

use std::collections::HashMap;
use std::sync::LazyLock;

use xc_character::job;
use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{Decoded, Field, Fields, Packet, S2C, World, row};

/// GP_GROUP_ATTR's bits, low first, as 0x0DD, 0x0E2, and each 0x0C8 entry send them.
const GATTR: [(&str, u32); 7] = [
    ("PartyNo", 0),
    ("PartyLeaderFlg", 2),
    ("AllianceLeaderFlg", 3),
    ("PartyRFlg", 4),
    ("AllianceRFlg", 5),
    ("unknown06", 6),
    ("unknown07", 7),
];

/// A field built once, its path kept for the life of the program.
fn field(op: u16, path: String) -> Field {
    Field::new(S2C, op, path.leak())
}

fn gattr_fields(op: u16, prefix: &str) -> [Field; 7] {
    GATTR.map(|(name, _)| field(op, format!("{prefix}{name}")))
}

/// A 0x0DD or 0x0E2 member's fields, then its GAttr's.
const MEMBER: [&str; 11] =
    ["UniqueNo", "Name", "MemberNumber", "ZoneNo", "mjob_no", "mjob_lv", "sjob_no", "sjob_lv", "Hpp", "Mpp", "Tp"];
static MEMBERS: LazyLock<[([Field; 11], [Field; 7]); 2]> =
    LazyLock::new(|| [0x0DD, 0x0E2].map(|op| (MEMBER.map(|k| field(op, k.to_string())), gattr_fields(op, "GAttr."))));

/// Each 0x0C8 slot's UniqueNo, ActIndex, ZoneNo, then its GAttr's.
static SLOTS: LazyLock<Vec<([Field; 3], [Field; 7])>> = LazyLock::new(|| {
    (0..20)
        .map(|i| {
            let g = format!("GroupTbl[{i}].");
            (["UniqueNo", "ActIndex", "ZoneNo"].map(|k| field(0x0C8, format!("{g}{k}"))), gattr_fields(0x0C8, &g))
        })
        .collect()
});

fn gattr(f: &dyn Fields, fields: &[Field; 7]) -> Option<i64> {
    let bits = fields.each_ref().map(|x| x.int(f));
    if bits.iter().all(Option::is_none) {
        return None;
    }
    Some(bits.iter().zip(GATTR).map(|(v, (_, shift))| v.unwrap_or(0) << shift).sum())
}

/// Any NPC id, 0x01ZZZIII, in the party list: a Trust, or an Adventuring Fellow, which reads as one.
pub fn is_trust(id: Option<i64>) -> bool {
    id.is_some_and(|i| i >> 24 == 1)
}

pub static META: Meta = Meta {
    name: "party",
    version: 3,
    reads: &[(S2C, 0x0DD), (S2C, 0x0E2), (S2C, 0x0C8)],
    // It reads only the world's packets.
    sparse: false,
    tables: &[Table {
        name: "party",
        columns: &[
            ("member_id", I64),
            ("name", Str),
            ("member_number", I32),
            ("list", Str),
            ("zone_id", I32),
            ("trust", Bool),
            ("main_job", Str),
            ("main_level", I32),
            ("sub_job", Str),
            ("sub_level", I32),
            ("hpp", I32),
            ("mpp", I32),
            ("tp", I32),
            ("flags", I64),
        ],
    }],
};

#[derive(Default)]
pub struct Party {
    /// Member id -> the name a party list gave it.
    names: HashMap<i64, String>,
}

impl Extractor for Party {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        if p.opcode == 0x0C8 {
            for (i, ([uid, index, zone], g)) in SLOTS.iter().enumerate() {
                let Some(uid) = uid.int(f).filter(|&u| u != 0) else { continue };
                let name = self.names.get(&uid).map(String::as_str).or_else(|| {
                    let e = world.entities.get(&index.int(f))?;
                    if e.id == Some(uid) { e.name.as_deref() } else { None }
                });
                out.emit(
                    "party",
                    Some(p),
                    row! {
                        member_id: uid,
                        name: name,
                        member_number: i,
                        list: "alliance",
                        zone_id: zone.int(f),
                        trust: is_trust(Some(uid)),
                        flags: gattr(f, g),
                    },
                );
            }
            return;
        }
        let (m, g) = &MEMBERS[usize::from(p.opcode == 0x0E2)];
        let [uid, _, number, zone, mjob, mlv, sjob, slv, hpp, mpp, tp] = m.each_ref().map(|x| x.int(f));
        let name = m[1].text(f).filter(|n| !n.is_empty());
        if let (Some(u), Some(n)) = (uid, &name) {
            self.names.insert(u, n.clone());
        }
        out.emit(
            "party",
            Some(p),
            row! {
                member_id: uid,
                name: name,
                member_number: number,
                list: "party",
                zone_id: zone,
                trust: is_trust(uid),
                main_job: job(mjob),
                main_level: mlv,
                sub_job: job(sjob),
                sub_level: slv,
                hpp: hpp,
                mpp: mpp,
                tp: tp,
                flags: gattr(f, g),
            },
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{PLAYER, raw};

    /// Curilla in Apollyon, as retail sent her.
    const TRUST: i64 = 0x01000000 | (0x026 << 12) | 0x63C;

    /// A 0x0DD or 0x0E2 party member (one layout).
    #[allow(clippy::too_many_arguments)]
    fn member(
        op: u16,
        uid: i64,
        index: u16,
        name: &str,
        number: u8,
        gattr: u32,
        zone: u16,
        job: u8,
        level: u8,
    ) -> (u16, Vec<u8>) {
        let mut d = vec![0u8; 56];
        (d[0], d[1]) = (op as u8, (56 / 4) << 1);
        for (i, v) in [uid as u32, 1000, 100, 0, gattr].into_iter().enumerate() {
            d[4 + 4 * i..8 + 4 * i].copy_from_slice(&v.to_le_bytes());
        }
        d[24..26].copy_from_slice(&index.to_le_bytes());
        d[26] = number;
        d[32..34].copy_from_slice(&zone.to_le_bytes());
        (d[34], d[35]) = (job, level);
        d[40..40 + name.len()].copy_from_slice(name.as_bytes());
        (op, d)
    }

    /// A 0x0C8 alliance list: (id, index, flags, zone) per slot.
    fn alliance(entries: &[(i64, u16, u8, u16)]) -> (u16, Vec<u8>) {
        let mut d = vec![0u8; 8 + 20 * 12];
        (d[0], d[1]) = (0xC8, ((d.len() / 4) << 1) as u8);
        for (i, &(uid, index, flags, zone)) in entries.iter().enumerate() {
            let o = 8 + 12 * i;
            d[o..o + 4].copy_from_slice(&(uid as u32).to_le_bytes());
            d[o + 4..o + 6].copy_from_slice(&index.to_le_bytes());
            d[o + 6] = flags;
            d[o + 8..o + 10].copy_from_slice(&zone.to_le_bytes());
        }
        (0x0C8, d)
    }

    #[test]
    fn members_and_trusts_from_every_list() {
        let at = |ts, (op, d): (u16, Vec<u8>)| (ts, S2C, op, d);
        let out = raw(
            Box::new(Party::default()),
            vec![
                at(0, member(0xDD, PLAYER, 0x464, "Friend", 1, 4, 0, 1, 75)),
                at(1000, member(0xE2, TRUST, 0x73C, "Curilla", 2, 0, 0x026, 0, 0)),
                at(
                    2000,
                    alliance(&[(PLAYER, 0x464, 4, 0x026), (TRUST, 0x73C, 0, 0x026), (0x0001_0003, 0x465, 0, 0x026)]),
                ),
            ],
            PLAYER,
        );
        let r = out.rows("party");
        let got: Vec<_> = (0..r.len())
            .map(|i| ["member_id", "name", "member_number", "trust", "flags"].map(|k| r.get(i, k)))
            .collect();
        let row = |id: i64, name: Option<&str>, n: i64, trust: bool, flags: i64| {
            [V::Int(id), name.into(), V::Int(n), V::Bool(trust), V::Int(flags)]
        };
        assert_eq!(
            got,
            [
                row(PLAYER, Some("Friend"), 1, false, 4),
                row(TRUST, Some("Curilla"), 2, true, 0),
                row(PLAYER, Some("Friend"), 0, false, 4),
                row(TRUST, Some("Curilla"), 1, true, 0),
                row(0x0001_0003, None, 2, false, 0),
            ]
        );
        assert_eq!(
            (r.get(0, "main_job"), r.get(0, "main_level"), r.get(2, "zone_id")),
            ("WAR".into(), V::Int(75), V::Int(0x026))
        );
    }
}
