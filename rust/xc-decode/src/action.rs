//! The action packet's bitstream (s2c 0x028), as ffxi_packets' `_action`: bits past the packet's end read
//! as zero, so a short packet decodes. Targets and results are read in order as they are iterated.

use crate::Value;

pub(crate) const PREFIX: &str = "action (decoded bitstream).";

/// LSB-first bits from a byte slice; bits past the end read as zero.
#[derive(Clone, Copy, Debug)]
struct Reader<'a> {
    raw: &'a [u8],
    pos: usize,
}

impl Reader<'_> {
    #[inline]
    fn read(&mut self, n: u32) -> u32 {
        let (start, shift) = (self.pos >> 3, (self.pos & 7) as u32);
        self.pos += n as usize;
        let mut b = [0u8; 8];
        if let Some(src) = self.raw.get(start..) {
            let k = src.len().min(8);
            b[..k].copy_from_slice(&src[..k]);
        }
        ((u64::from_le_bytes(b) >> shift) & ((1u64 << n) - 1)) as u32
    }
}

/// The action packet's head; `targets()` reads the rest.
#[derive(Clone, Copy, Debug)]
pub struct Action<'a> {
    pub actor_id: u32,
    pub target_count: u32,
    pub result_sum: u32,
    pub cmd_no: u32,
    pub cmd_arg: u32,
    pub info: u32,
    r: Reader<'a>,
}

/// A target: its id, and `results()`.
#[derive(Clone, Copy, Debug)]
pub struct Target<'a> {
    pub target_id: u32,
    pub result_count: u32,
    r: Reader<'a>,
}

/// One result of a target.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ActionResult {
    pub miss: u32,
    pub kind: u32,
    pub sub_kind: u32,
    pub info: u32,
    pub scale: u32,
    pub value: u32,
    pub message: u32,
    pub bit: u32,
    pub proc: Option<Extra>,
    pub react: Option<Extra>,
}

/// An added effect (proc) or a reaction (react) of a result.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Extra {
    pub kind: u32,
    pub info: u32,
    pub value: u32,
    pub message: u32,
}

impl<'a> Action<'a> {
    /// None unless the packet starts with 0x28 and holds 5 bytes, as in Python.
    pub fn decode(raw: &'a [u8]) -> Option<Action<'a>> {
        if raw.len() < 5 || raw[0] != 0x28 {
            return None;
        }
        let mut r = Reader { raw, pos: 40 };
        Some(Action {
            actor_id: r.read(32),
            target_count: r.read(6),
            result_sum: r.read(4),
            cmd_no: r.read(4),
            cmd_arg: r.read(32),
            info: r.read(32),
            r,
        })
    }

    pub fn targets(&self) -> Targets<'a> {
        Targets { left: self.target_count, r: self.r }
    }

    /// Every path Python's decoder gives the bitstream, with its value.
    pub fn fields(&self) -> impl Iterator<Item = (String, Value<'a>)> + use<'a> {
        let v = |x: u32| Value::U(x as u64);
        let head = [
            ("actor_id", self.actor_id),
            ("target_count", self.target_count),
            ("result_sum", self.result_sum),
            ("cmd_no", self.cmd_no),
            ("cmd_arg", self.cmd_arg),
            ("info", self.info),
        ];
        let head = head.into_iter().map(move |(k, x)| (format!("{PREFIX}{k}"), v(x)));
        let rest = self.targets().enumerate().flat_map(move |(t, target)| {
            let tp = format!("{PREFIX}targets[{t}]");
            let mut out = vec![
                (format!("{tp}.target_id"), v(target.target_id)),
                (format!("{tp}.result_count"), v(target.result_count)),
            ];
            for (i, r) in target.results().enumerate() {
                let rp = format!("{tp}[{i}]");
                for (k, x) in [
                    ("miss", r.miss),
                    ("kind", r.kind),
                    ("sub_kind", r.sub_kind),
                    ("info", r.info),
                    ("scale", r.scale),
                    ("value", r.value),
                    ("message", r.message),
                    ("bit", r.bit),
                ] {
                    out.push((format!("{rp}.{k}"), v(x)));
                }
                for (g, e) in [("proc", r.proc), ("react", r.react)] {
                    if let Some(e) = e {
                        for (k, x) in [("kind", e.kind), ("info", e.info), ("value", e.value), ("message", e.message)] {
                            out.push((format!("{rp}.{g}.{k}"), v(x)));
                        }
                    }
                }
            }
            out
        });
        head.chain(rest)
    }
}

impl<'a> Target<'a> {
    pub fn results(&self) -> Results<'a> {
        Results { left: self.result_count, r: self.r }
    }
}

/// The action's targets, in order.
#[derive(Clone, Copy, Debug)]
pub struct Targets<'a> {
    left: u32,
    r: Reader<'a>,
}

impl<'a> Iterator for Targets<'a> {
    type Item = Target<'a>;
    fn next(&mut self) -> Option<Target<'a>> {
        if self.left == 0 {
            return None;
        }
        self.left -= 1;
        let target_id = self.r.read(32);
        let result_count = self.r.read(4);
        let t = Target { target_id, result_count, r: self.r };
        let mut results = t.results();
        for _ in results.by_ref() {}
        self.r = results.r;
        Some(t)
    }
}

/// A target's results, in order.
#[derive(Clone, Copy, Debug)]
pub struct Results<'a> {
    left: u32,
    r: Reader<'a>,
}

impl Iterator for Results<'_> {
    type Item = ActionResult;
    fn next(&mut self) -> Option<ActionResult> {
        if self.left == 0 {
            return None;
        }
        self.left -= 1;
        let r = &mut self.r;
        let mut out = ActionResult {
            miss: r.read(3),
            kind: r.read(2),
            sub_kind: r.read(12),
            info: r.read(5),
            scale: r.read(5),
            value: r.read(17),
            message: r.read(10),
            bit: r.read(31),
            proc: None,
            react: None,
        };
        if r.read(1) != 0 {
            out.proc = Some(Extra { kind: r.read(6), info: r.read(4), value: r.read(17), message: r.read(10) });
        }
        if r.read(1) != 0 {
            out.react = Some(Extra { kind: r.read(6), info: r.read(4), value: r.read(14), message: r.read(10) });
        }
        Some(out)
    }
}
