//! A fast raw parser and TXY formatter, measured beside the shared Python/NumPy I/O path (a report
//! only: HeLab reads and writes through `helab/convert/raw.py` and `txy.py`).
//!
//! `parse_strict` takes only what `raw.py`'s fast path takes: a whole file of `\d+,\d+` lines all
//! ended by `\r\n`, or all by `\n`. Anything else (and a number of more than 19 digits) gives
//! None, and the caller uses `raw.parse_raw`. An integer converts to the nearest double, ties to
//! even, as Python's `float(int)` does.
//!
//! `format_txy` is `txy.format_txy`: C's `%.8g` (shortest of `%.7e` and `%f` by C's rule, trailing
//! zeros dropped, exponent of two digits at least), `NaN`, `Inf`, `-Inf`, `,` between values and
//! `\n` after every row. Rust's `{:.7e}` rounds the exact binary value to 8 significant digits,
//! ties to even, as C's printf does.

use std::fmt::Write;

/// Channels and times in file order, or None when the file isn't strictly `\d+,\d+` lines with
/// one line ending.
pub fn parse_strict(data: &[u8]) -> Option<(Vec<f64>, Vec<f64>)> {
    let lines = data.iter().filter(|&&b| b == b'\n').count();
    let mut channels = Vec::with_capacity(lines);
    let mut times = Vec::with_capacity(lines);
    let crlf = match data.iter().position(|&b| b == b'\n') {
        None => return if data.is_empty() { Some((channels, times)) } else { None },
        Some(k) => k > 0 && data[k - 1] == b'\r',
    };
    let mut pos = 0;
    let end = data.len();
    while pos < end {
        let (channel, next) = digits(data, pos)?;
        if next >= end || data[next] != b',' {
            return None;
        }
        let (time, next) = digits(data, next + 1)?;
        pos = if crlf {
            if next + 1 < end && data[next] == b'\r' && data[next + 1] == b'\n' { next + 2 } else { return None }
        } else if next < end && data[next] == b'\n' {
            next + 1
        } else {
            return None;
        };
        channels.push(channel);
        times.push(time);
    }
    Some((channels, times))
}

/// One run of 1–19 ASCII digits from `pos`, as a double, and the index after it.
#[inline]
fn digits(data: &[u8], pos: usize) -> Option<(f64, usize)> {
    let mut value: u64 = 0;
    let mut k = pos;
    while k < data.len() && data[k].is_ascii_digit() {
        if k - pos == 19 {
            return None;
        }
        value = value * 10 + u64::from(data[k] - b'0');
        k += 1;
    }
    if k == pos { None } else { Some((value as f64, k)) }
}

/// `%.8g`, with MATLAB's spellings of the non-finite values.
pub fn format_value(out: &mut String, value: f64) {
    if value.is_nan() {
        out.push_str("NaN");
        return;
    }
    if value.is_infinite() {
        out.push_str(if value > 0.0 { "Inf" } else { "-Inf" });
        return;
    }
    if value == 0.0 {
        out.push_str(if value.is_sign_negative() { "-0" } else { "0" });
        return;
    }
    // d.ddddddde±x, rounded once: C takes the exponent x of this conversion to choose the style.
    let mut scientific = String::with_capacity(24);
    write!(scientific, "{:.7e}", value).unwrap();
    let (mantissa, exponent) = scientific.split_once('e').unwrap();
    let exponent: i32 = exponent.parse().unwrap();
    let (negative, mantissa) = match mantissa.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, mantissa),
    };
    let digits: Vec<u8> = mantissa.bytes().filter(u8::is_ascii_digit).collect();
    let significant = digits.iter().rposition(|&d| d != b'0').map_or(1, |k| k + 1);
    let digits = &digits[..significant];
    if negative {
        out.push('-');
    }
    if (-4..8).contains(&exponent) {
        // %f with 7 − x decimals, trailing zeros dropped.
        if exponent < 0 {
            out.push_str("0.");
            for _ in 0..(-exponent - 1) {
                out.push('0');
            }
            out.extend(digits.iter().map(|&d| d as char));
        } else {
            let whole = exponent as usize + 1;
            for k in 0..whole {
                out.push(if k < digits.len() { digits[k] as char } else { '0' });
            }
            if digits.len() > whole {
                out.push('.');
                out.extend(digits[whole..].iter().map(|&d| d as char));
            }
        }
    } else {
        out.push(digits[0] as char);
        if digits.len() > 1 {
            out.push('.');
            out.extend(digits[1..].iter().map(|&d| d as char));
        }
        write!(out, "e{}{:02}", if exponent < 0 { '-' } else { '+' }, exponent.abs()).unwrap();
    }
}

/// `rows × 3` values, row-major, as TXY text.
pub fn format_txy(values: &[f64]) -> String {
    let mut out = String::with_capacity(values.len() * 16);
    for row in values.chunks(3) {
        for (k, &value) in row.iter().enumerate() {
            if k > 0 {
                out.push(',');
            }
            format_value(&mut out, value);
        }
        out.push('\n');
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn g(value: f64) -> String {
        let mut out = String::new();
        format_value(&mut out, value);
        out
    }

    #[test]
    fn formats_like_c() {
        assert_eq!(g(0.125), "0.125");
        assert_eq!(g(123456785.0), "1.2345678e+08");
        assert_eq!(g(123456795.0), "1.234568e+08");
        assert_eq!(g(1e-5), "1e-05");
        assert_eq!(g(0.0001), "0.0001");
        assert_eq!(g(-12345678.0), "-12345678");
        assert_eq!(g(1e100), "1e+100");
        assert_eq!(g(-0.0), "-0");
    }

    #[test]
    fn strict_files_only() {
        assert_eq!(parse_strict(b"1,2\r\n3,4\r\n"), Some((vec![1.0, 3.0], vec![2.0, 4.0])));
        assert_eq!(parse_strict(b"1,2\n"), Some((vec![1.0], vec![2.0])));
        assert_eq!(parse_strict(b"1,2\r\n3,4\n"), None);
        assert_eq!(parse_strict(b"1,2"), None);
        assert_eq!(parse_strict(b""), Some((vec![], vec![])));
    }
}
