//! tests/battle/test_combat.py's packet builders: real bytes for raw(), so the decoder and Resends see them.

/// A result: test_combat.py's r(). proc is (value, message), react (value, message).
#[derive(Clone, Debug, Default)]
pub struct R {
    pub message: i64,
    pub value: i64,
    pub sub_kind: i64,
    pub bit: i64,
    pub proc: Option<(i64, i64)>,
    pub react: Option<(i64, i64)>,
    pub miss: i64,
}

/// r(message, value); the rest by `R { miss: 4, ..r(1, 15) }`.
pub fn r(message: i64, value: i64) -> R {
    R { message, value, ..R::default() }
}

/// LSB-first bits, as the decoder reads them.
#[derive(Default)]
struct Bits {
    body: Vec<u8>,
    n: usize,
}

impl Bits {
    fn w(&mut self, v: i64, bits: usize) {
        for b in 0..bits {
            if self.n.is_multiple_of(8) {
                self.body.push(0);
            }
            self.body[self.n / 8] |= (((v >> b) & 1) as u8) << (self.n % 8);
            self.n += 1;
        }
    }
}

/// A 0x028 packet: the bitstream the decoder reads, LSB first from byte 5.
pub fn act(actor: i64, cat: i64, arg: i64, targets: &[(i64, Vec<R>)]) -> (u16, Vec<u8>) {
    let mut b = Bits::default();
    for (v, bits) in [(actor, 32), (targets.len() as i64, 6), (0, 4), (cat, 4), (arg, 32), (0, 32)] {
        b.w(v, bits);
    }
    for (tid, results) in targets {
        b.w(*tid, 32);
        b.w(results.len() as i64, 4);
        for x in results {
            for (v, bits) in
                [(x.miss, 3), (0, 2), (x.sub_kind, 12), (0, 5), (0, 5), (x.value, 17), (x.message, 10), (x.bit, 31)]
            {
                b.w(v, bits);
            }
            for (extra, vbits) in [(x.proc, 17), (x.react, 14)] {
                b.w(extra.is_some() as i64, 1);
                if let Some((value, message)) = extra {
                    for (v, bits) in [(0, 6), (0, 4), (value, vbits), (message, 10)] {
                        b.w(v, bits);
                    }
                }
            }
        }
    }
    let size = (5 + b.body.len()).div_ceil(4) * 4;
    let mut data = vec![0u8; size];
    (data[0], data[1], data[4]) = (0x28, ((size / 4) << 1) as u8, b.body.len() as u8);
    data[5..5 + b.body.len()].copy_from_slice(&b.body);
    (0x028, data)
}

fn put(data: &mut [u8], at: usize, xs: &[u32]) {
    for (i, x) in xs.iter().enumerate() {
        data[at + 4 * i..at + 4 * i + 4].copy_from_slice(&x.to_le_bytes());
    }
}

/// A 0x029 battle message.
pub fn message(caster: i64, target: i64, num: i64, data1: i64, data2: i64) -> (u16, Vec<u8>) {
    let mut data = vec![0u8; 28];
    (data[0], data[1]) = (0x29, (28 / 4) << 1);
    put(&mut data, 4, &[caster as u32, target as u32, data1 as u32, data2 as u32]);
    for (i, h) in [1, target & 0xFFF, num].into_iter().enumerate() {
        data[20 + 2 * i..22 + 2 * i].copy_from_slice(&(h as u16).to_le_bytes());
    }
    (0x029, data)
}

/// A 0x0DF party update: a member's HP, MP, and TP.
pub fn vitals(tp: i64, who: i64) -> (u16, Vec<u8>) {
    let mut data = vec![0u8; 40];
    (data[0], data[1]) = (0xDF, (40 / 4) << 1);
    put(&mut data, 4, &[who as u32, 1000, 100, tp as u32]);
    (0x0DF, data)
}

/// A 0x037: the character's own status, which names its id.
pub fn status(who: i64) -> (u16, Vec<u8>) {
    let mut data = vec![0u8; 48];
    (data[0], data[1]) = (0x37, (48 / 4) << 1);
    put(&mut data, 36, &[who as u32]);
    (0x037, data)
}

/// One of raw()'s packets: an s2c packet at ts.
pub fn at(ts: i64, (op, data): (u16, Vec<u8>)) -> (i64, u8, u16, Vec<u8>) {
    (ts, 0, op, data)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Fields;

    #[test]
    fn they_decode_as_built() {
        let (op, data) = act(7, 1, 300, &[(9, vec![R { miss: 4, react: Some((30, 33)), ..r(1, 15) }])]);
        let p = xc_decode::decode(0, op, &data, None).unwrap();
        let a = Fields::action(&p);
        let x = &a.targets[0].results[0];
        assert_eq!((a.actor_id, a.cmd_no, a.cmd_arg, a.targets[0].id), (Some(7), Some(1), Some(300), Some(9)));
        assert_eq!(
            (x.miss, x.value, x.message, x.react.as_ref().and_then(|e| e.message)),
            (Some(4), Some(15), Some(1), Some(33))
        );
        let (op, data) = message(7, 9, 6, 300, 0);
        let p = xc_decode::decode(0, op, &data, None).unwrap();
        assert_eq!(
            (p.int("UniqueNoCas"), p.int("UniqueNoTar"), p.int("MessageNum"), p.int("Data")),
            (Some(7), Some(9), Some(6), Some(300))
        );
        let (op, data) = vitals(121, 9);
        assert_eq!(xc_decode::decode(0, op, &data, None).unwrap().int("Tp"), Some(121));
        let (op, data) = status(9);
        assert_eq!(xc_decode::decode(0, op, &data, None).unwrap().int("UniqueNo"), Some(9));
    }
}
