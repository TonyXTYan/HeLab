//! `helab_convert_rs`: the rust backend of HeLab's TXY converter (`helab/convert/backends/rust.py`
//! is its typed wrapper and registers it). Every function copies its inputs while it holds the
//! GIL and releases the GIL for the work, so threads converting different shots run in parallel.

use numpy::{IntoPyArray, PyArray1, PyArray2, PyArrayMethods, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

mod rawio;
pub mod reconstruct;

use reconstruct::Params;

type Array<'py> = Bound<'py, PyArray1<f64>>;

/// The hits (an `(n, 3)` float64 array, sorted by T) and the number of pieces matched. The
/// profile arrives unpacked (`rust.py`'s `_params`); `threads` and `piece_rows` split the shot
/// (`reconstruct::cut_points`).
#[pyfunction]
#[pyo3(name = "reconstruct", signature = (channels, times, channel_corners, subtract_time_zero, skip_first_sorted_row, dead_time_bins,
                    search_depth, search_window, x_limit, y_limit, xy_limit, time_sum_t, bin_time, v_perp, centred,
                    matlab_overflow_row, threads=1, piece_rows=0))]
#[allow(clippy::too_many_arguments)]
fn py_reconstruct<'py>(
    py: Python<'py>,
    channels: PyReadonlyArray1<'py, f64>,
    times: PyReadonlyArray1<'py, f64>,
    channel_corners: (f64, f64, f64, f64),
    subtract_time_zero: bool,
    skip_first_sorted_row: bool,
    dead_time_bins: (Option<f64>, Option<f64>, Option<f64>, Option<f64>),
    search_depth: usize,
    search_window: f64,
    x_limit: f64,
    y_limit: f64,
    xy_limit: f64,
    time_sum_t: (f64, f64),
    bin_time: f64,
    v_perp: (f64, f64),
    centred: bool,
    matlab_overflow_row: bool,
    threads: usize,
    piece_rows: usize,
) -> PyResult<(Bound<'py, PyArray2<f64>>, usize)> {
    let (channels, times) = (channels.as_slice()?, times.as_slice()?);
    if channels.len() != times.len() {
        return Err(PyValueError::new_err("channels and times differ in length"));
    }
    let rows = reconstruct::file_rows(channels, times);
    let params = Params {
        channel_x1: channel_corners.0,
        channel_x2: channel_corners.1,
        channel_y1: channel_corners.2,
        channel_y2: channel_corners.3,
        subtract_time_zero,
        skip_first_sorted_row,
        dead_time_bins: [dead_time_bins.0, dead_time_bins.1, dead_time_bins.2, dead_time_bins.3],
        search_depth,
        search_window,
        x_limit,
        y_limit,
        xy_limit,
        time_sum_t_x: time_sum_t.0,
        time_sum_t_y: time_sum_t.1,
        bin_time,
        v_perp_x: v_perp.0,
        v_perp_y: v_perp.1,
        centred,
        matlab_overflow_row,
    };
    let (hits, pieces) = py.detach(|| reconstruct::reconstruct_rows(rows, &params, threads, piece_rows));
    let rows = hits.len() / 3;
    Ok((hits.into_pyarray(py).reshape([rows, 3])?, pieces))
}

/// The piece bounds `reconstruct` would use on these sorted times (for tests).
#[pyfunction(name = "cut_points")]
fn py_cut_points(times: PyReadonlyArray1<'_, f64>, window: f64, piece_rows: usize) -> PyResult<Vec<usize>> {
    Ok(reconstruct::cut_points(times.as_slice()?, window, piece_rows))
}

/// `(channels, times)` of a strict raw file (`raw.py`'s fast path), or None for any other file.
#[pyfunction(name = "parse_strict")]
fn py_parse_strict<'py>(py: Python<'py>, data: &[u8]) -> Option<(Array<'py>, Array<'py>)> {
    let data = data.to_vec();
    let (channels, times) = py.detach(|| rawio::parse_strict(&data))?;
    Some((channels.into_pyarray(py), times.into_pyarray(py)))
}

/// `txy.format_txy` of an `(n, 3)` float64 array.
#[pyfunction(name = "format_txy")]
fn py_format_txy<'py>(py: Python<'py>, hits: PyReadonlyArray1<'py, f64>) -> PyResult<Bound<'py, PyBytes>> {
    let values = hits.as_slice()?.to_vec();
    let text = py.detach(|| rawio::format_txy(&values));
    Ok(PyBytes::new(py, text.as_bytes()))
}

#[pymodule]
fn helab_convert_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_reconstruct, m)?)?;
    m.add_function(wrap_pyfunction!(py_cut_points, m)?)?;
    m.add_function(wrap_pyfunction!(py_parse_strict, m)?)?;
    m.add_function(wrap_pyfunction!(py_format_txy, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
