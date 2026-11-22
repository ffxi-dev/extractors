//! Python's arithmetic where Rust's differs in the last bit or on ties: the extractors' rows must match
//! Python's to the bit, since the pins hash them.

/// Python's round(x): half to even.
pub fn round(x: f64) -> i64 {
    x.round_ties_even() as i64
}

/// Python's round(x, n): the double nearest the decimal x rounds to, half to even on the exact binary value,
/// as CPython's dtoa does. Rust formats a float exactly, rounding ties to even, so formatting and parsing back
/// gives the same.
pub fn round_to(x: f64, n: usize) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.n$}").parse().unwrap()
}

/// Python's a % b for floats: the sign of b.
pub fn fmod(a: f64, b: f64) -> f64 {
    let m = a % b;
    if m != 0.0 && (b < 0.0) != (m < 0.0) {
        m + b
    } else if m == 0.0 {
        0.0f64.copysign(b)
    } else {
        m
    }
}

/// Python's a // b for ints: floored.
pub fn floordiv(a: i64, b: i64) -> i64 {
    a.div_euclid(b) - if b < 0 && a.rem_euclid(b) != 0 { 1 } else { 0 }
}

/// Python's a % b for ints: the sign of b.
pub fn intmod(a: i64, b: i64) -> i64 {
    a - b * floordiv(a, b)
}

/// math.dist(p, q).
pub fn dist(p: &[f64], q: &[f64]) -> f64 {
    let d: Vec<f64> = p.iter().zip(q).map(|(a, b)| (a - b).abs()).collect();
    norm(&d)
}

/// math.dist of two points in 3D.
pub fn dist3(p: (f64, f64, f64), q: (f64, f64, f64)) -> f64 {
    dist(&[p.0, p.1, p.2], &[q.0, q.1, q.2])
}

/// math.hypot(*xs).
pub fn hypot(xs: &[f64]) -> f64 {
    let d: Vec<f64> = xs.iter().map(|x| x.abs()).collect();
    norm(&d)
}

/// CPython 3.13's vector_norm (Modules/mathmodule.c): the scaled, compensated sum it computes dist and hypot
/// with, so a result matches Python's to the bit. xs are absolute values.
fn norm(xs: &[f64]) -> f64 {
    let mut max = 0.0f64;
    let mut nan = false;
    for &x in xs {
        nan |= x.is_nan();
        if x > max {
            max = x;
        }
    }
    if max.is_infinite() {
        return max;
    }
    if nan {
        return f64::NAN;
    }
    if max == 0.0 || xs.len() <= 1 {
        return max;
    }
    let (_, max_e) = frexp(max);
    if max_e < -1023 {
        let scaled: Vec<f64> = xs.iter().map(|x| x / f64::MIN_POSITIVE).collect();
        return f64::MIN_POSITIVE * norm(&scaled);
    }
    let scale = ldexp(1.0, -max_e);
    let (mut csum, mut frac1, mut frac2) = (1.0f64, 0.0f64, 0.0f64);
    for &x in xs {
        let x = x * scale;
        let (hi, lo) = mul(x, x);
        let (s, slo) = fast_sum(csum, hi);
        csum = s;
        frac1 += lo;
        frac2 += slo;
    }
    let mut h = (csum - 1.0 + (frac1 + frac2)).sqrt();
    let (hi, lo) = mul(-h, h);
    let (s, slo) = fast_sum(csum, hi);
    csum = s;
    frac1 += lo;
    frac2 += slo;
    let x = csum - 1.0 + (frac1 + frac2);
    h += x / (2.0 * h);
    h / scale
}

fn mul(x: f64, y: f64) -> (f64, f64) {
    let z = x * y;
    (z, x.mul_add(y, -z))
}

fn fast_sum(a: f64, b: f64) -> (f64, f64) {
    let x = a + b;
    let z = x - a;
    (x, b - z)
}

/// C's frexp for a finite, positive x: (m, e) with x = m * 2^e, m in [0.5, 1).
fn frexp(x: f64) -> (f64, i32) {
    let bits = x.to_bits();
    let exp = ((bits >> 52) & 0x7FF) as i32;
    if exp == 0 {
        let (m, e) = frexp(x * 2f64.powi(64));
        return (m, e - 64);
    }
    (f64::from_bits((bits & !(0x7FF << 52)) | (1022 << 52)), exp - 1022)
}

/// C's ldexp(x, e) for the powers of two vector_norm scales by.
fn ldexp(x: f64, e: i32) -> f64 {
    // Two steps keep each factor a normal double.
    let half = e / 2;
    x * 2f64.powi(half) * 2f64.powi(e - half)
}

#[cfg(test)]
mod tests {
    use super::*;

    // Values from CPython 3.13.
    #[test]
    fn rounds_as_python() {
        assert_eq!((round(0.5), round(1.5), round(2.5), round(-0.5)), (0, 2, 2, 0));
        assert_eq!(round_to(2.675, 2), 2.67); // 2.675 is below the tie in binary
        assert_eq!(round_to(0.125, 2), 0.12);
        assert_eq!(round_to(0.375, 2), 0.38);
        assert_eq!(round_to(1.00005, 4), 1.0001);
    }

    #[test]
    fn mods_as_python() {
        assert_eq!(fmod(-1.0, 360.0), 359.0);
        assert_eq!(fmod(361.0, 360.0), 1.0);
        assert_eq!(fmod(-360.0, 360.0).to_bits(), 0.0f64.to_bits());
        assert_eq!((floordiv(-7, 2), intmod(-7, 2), floordiv(7, -2), intmod(7, -2)), (-4, 1, -4, -1));
    }

    #[test]
    fn dist_as_python() {
        // math.dist((0.1, 0.2, 0.3), (1.7, -2.9, 33.25)) and math.hypot(3, 4) in CPython 3.13.
        assert_eq!(dist(&[0.1, 0.2, 0.3], &[1.7, -2.9, 33.25]).to_bits(), 33.134159111104665f64.to_bits());
        assert_eq!(hypot(&[3.0, 4.0]), 5.0);
        assert_eq!(dist(&[1.0], &[-2.0]), 3.0);
        assert_eq!(dist(&[0.0, 0.0], &[0.0, 0.0]), 0.0);
    }
}
