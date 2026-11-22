//! index.walk: one pass over a capture's packets, decoding only the world's opcodes and those the extractors
//! read; the world reads each first, then each extractor that reads it.

use std::path::Path;

use crate::capture::{Info, Reader};
use crate::extract::{Extractor, Out};
use crate::packet::{Decoded, Fields, NoFields, Packet};
use crate::world::{WORLD, World};

/// The largest capture read, as Mogsafe limits a capture.
pub const MAX_PACKETS: u64 = 60_000_000;

#[derive(Debug)]
pub enum Error {
    /// xicap could not read the capture.
    Read(String),
    /// Over MAX_PACKETS: Python's Skipped(TOO_LARGE).
    TooLarge,
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Error::Read(e) => f.write_str(e),
            Error::TooLarge => f.write_str("Not analysed: over 60,000,000 packets"),
        }
    }
}

impl std::error::Error for Error {}

/// Something that sees every packet, every channel, after the world: the decode unit's CaptureStats.
pub trait See {
    fn see(&mut self, p: &Packet, world: &World);
}

/// Which extractors read each (direction, opcode), and whether the world does.
struct Dispatch {
    slot: Vec<u16>, // (direction << 16 | opcode) -> 1 + its index in lists, 0 when nothing reads it
    lists: Vec<(bool, Vec<usize>)>,
}

impl Dispatch {
    fn new(xs: &[Box<dyn Extractor>]) -> Dispatch {
        let mut d = Dispatch { slot: vec![0; 2 << 16], lists: Vec::new() };
        for &key in &WORLD {
            d.list(key).0 = true;
        }
        for (i, x) in xs.iter().enumerate() {
            for &key in x.meta().reads {
                d.list(key).1.push(i);
            }
        }
        d
    }

    fn list(&mut self, (dir, op): (u8, u16)) -> &mut (bool, Vec<usize>) {
        let s = &mut self.slot[(dir as usize) << 16 | op as usize];
        if *s == 0 {
            self.lists.push((false, Vec::new()));
            *s = self.lists.len() as u16;
        }
        &mut self.lists[*s as usize - 1]
    }

    fn get(&self, p: &Packet) -> Option<&(bool, Vec<usize>)> {
        match self.slot[(p.direction as usize & 1) << 16 | p.opcode as usize] {
            0 => None,
            s => Some(&self.lists[s as usize - 1]),
        }
    }
}

/// Packets in capture order: a capture's reader, or a test's packets.
pub trait Source {
    /// The next packet, or None at the end. It borrows the source until the next call.
    fn next_packet(&mut self) -> Result<Option<Packet<'_>>, Error>;
}

impl Source for Reader {
    fn next_packet(&mut self) -> Result<Option<Packet<'_>>, Error> {
        self.next().map_err(Error::Read)
    }
}

/// Walk a capture with these extractors: the header, the world at the end, and each extractor's rows.
pub fn walk(
    path: &Path,
    xs: &mut [Box<dyn Extractor>],
    see: Option<&mut dyn See>,
) -> Result<(Info, World, Vec<Out>), Error> {
    let mut r = Reader::open(path).map_err(Error::Read)?;
    let info = r.info.clone();
    let mut world = World::new(info.character_id as i64, &info.character);
    let outs = walk_packets(&mut r, &info.client_version, &mut world, xs, see)?;
    Ok((info, world, outs))
}

/// The walk over any packets, from the world as it stands.
pub fn walk_packets(
    src: &mut dyn Source,
    client_version: &str,
    world: &mut World,
    xs: &mut [Box<dyn Extractor>],
    mut see: Option<&mut dyn See>,
) -> Result<Vec<Out>, Error> {
    let dispatch = Dispatch::new(xs);
    let mut outs: Vec<Out> = xs.iter().map(|x| Out::new(x.meta())).collect();
    while let Some(p) = src.next_packet()? {
        if p.idx >= MAX_PACKETS {
            return Err(Error::TooLarge);
        }
        if p.channel == 0
            && let Some((in_world, readers)) = dispatch.get(&p)
        {
            let decoded = xc_decode::decode(p.direction, p.opcode, p.data, Some(client_version));
            let f: &dyn Fields = match &decoded {
                Some(d) => d,
                None => &NoFields,
            };
            let f = Decoded::new(f);
            if *in_world {
                world.update(&p, &*f);
            }
            for &i in readers {
                xs[i].packet(&p, &f, world, &mut outs[i]);
            }
        }
        if let Some(s) = see.as_deref_mut() {
            s.see(&p, world);
        }
    }
    for (x, out) in xs.iter_mut().zip(&mut outs) {
        x.finish(world, out);
    }
    Ok(outs)
}
