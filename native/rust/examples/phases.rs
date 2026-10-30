// Phase timings of reconstruct on one raw file (dev only): cargo run --release --example phases -- FILE
use helab_convert_rs::reconstruct::{cut_points, file_rows, prepare, reconstruct, Params};
use std::time::Instant;

fn main() {
    let path = std::env::args().nth(1).expect("raw file");
    let data = std::fs::read(path).unwrap();
    let text = String::from_utf8(data).unwrap();
    let (mut ch, mut t) = (Vec::new(), Vec::new());
    for line in text.lines() {
        let (a, b) = line.trim_end().split_once(',').unwrap();
        ch.push(a.parse::<f64>().unwrap());
        t.push(b.parse::<f64>().unwrap());
    }
    let p = Params { channel_x1: 0.0, channel_x2: 1.0, channel_y1: 2.0, channel_y2: 3.0, subtract_time_zero: true,
        skip_first_sorted_row: true, dead_time_bins: [None; 4], search_depth: 36, search_window: 3200.0,
        x_limit: 3400.0, y_limit: 3400.0, xy_limit: 400.0, time_sum_t_x: 3200.0, time_sum_t_y: 3200.0,
        bin_time: 25e-12, v_perp_x: 5.2632e5, v_perp_y: 5.2632e5, centred: true, matlab_overflow_row: true };
    let sorted_already = t.windows(2).filter(|w| w[0] > w[1]).count();
    for _ in 0..3 {
        let a = Instant::now();
        let s = prepare(file_rows(&ch, &t), &p);
        let b = Instant::now();
        let cuts = cut_points(&s.t, 3200.0, 1).len();
        let c = Instant::now();
        let (hits, _) = reconstruct(&ch, &t, &p, 1, 0);
        let d = Instant::now();
        let (_, pieces) = reconstruct(&ch, &t, &p, 4, 0);
        let e = Instant::now();
        println!("rows {} descents {} prepare {:?} cut_points(all) {:?} ({} pieces) whole x1 {:?} whole x4 {:?} ({} pieces) hits {}",
            t.len(), sorted_already, b - a, c - b, cuts, d - c, e - d, pieces, hits.len() / 3);
    }
}
