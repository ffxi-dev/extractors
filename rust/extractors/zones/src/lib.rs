//! world/zones.py: each zone-in (0x00A), and the zone server the 0x00B before it named. Its Python twin keeps
//! the docs.

use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

pub static META: Meta = Meta {
    name: "zones",
    version: 3,
    reads: &[(S2C, 0x00A), (S2C, 0x00B)],
    sparse: false,
    tables: &[Table { name: "zones", columns: &[("zone_id", I32), ("server", Str)] }],
};

static ZONE: Field = Field::new(S2C, 0x00A, "ZoneNo");
static STATE: Field = Field::new(S2C, 0x00B, "LogoutState");
static IWASAKI: [Field; 6] = [
    Field::new(S2C, 0x00B, "Iwasaki[0]"),
    Field::new(S2C, 0x00B, "Iwasaki[1]"),
    Field::new(S2C, 0x00B, "Iwasaki[2]"),
    Field::new(S2C, 0x00B, "Iwasaki[3]"),
    Field::new(S2C, 0x00B, "Iwasaki[4]"),
    Field::new(S2C, 0x00B, "Iwasaki[5]"),
];

/// The zone server 0x00B points the client to, address:port; none when the packet ends before it.
fn server(f: &Decoded) -> Option<String> {
    let mut b = [0; 6];
    for (v, x) in b.iter_mut().zip(&IWASAKI) {
        *v = x.int(f)?;
    }
    Some(format!("{}.{}.{}.{}:{}", b[0], b[1], b[2], b[3], b[4] | b[5] << 8))
}

#[derive(Default)]
pub struct Zones {
    next: Option<String>,
}

impl Extractor for Zones {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, _world: &World, out: &mut Out) {
        if p.opcode == 0x00B {
            // LogoutState 2 is a zone change; a logout's next zone-in comes via the lobby.
            self.next = if STATE.int(f) == Some(2) { server(f) } else { None };
            return;
        }
        out.emit("zones", Some(p), row! { zone_id: ZONE.int(f), server: self.next.take() });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::raw;

    /// A 0x00B: the logout state and as much of the zone server as given; no state, a bare header.
    fn logout(state: Option<u32>, server: &[u8]) -> Vec<u8> {
        let mut d = vec![0x0B, 0, 0, 0];
        if let Some(s) = state {
            d.extend(s.to_le_bytes());
            d.extend(server);
        }
        d
    }

    fn servers(logout: Vec<u8>) -> V {
        let mut zone_in = vec![0u8; 16];
        zone_in[0] = 0x0A;
        zone_in[4] = 230;
        let out = raw(Box::new(Zones::default()), vec![(0, S2C, 0x00B, logout), (1, S2C, 0x00A, zone_in)], 1);
        let r = out.rows("zones");
        assert_eq!((r.len(), r.get(0, "zone_id")), (1, V::Int(230)));
        r.get(0, "server")
    }

    #[test]
    fn a_zone_change_names_its_server_and_a_short_one_none() {
        let mut full = vec![10, 20, 30, 40];
        full.extend(54230u16.to_le_bytes());
        full.extend([0; 14]);
        assert_eq!(servers(logout(Some(2), &full)), V::Str("10.20.30.40:54230".into()));
        assert_eq!(servers(logout(None, &[])), V::Null);
        assert_eq!(servers(logout(Some(2), &full[..5])), V::Null);
        assert_eq!(servers(logout(Some(1), &full)), V::Null);
    }
}
