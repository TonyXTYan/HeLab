# Cache export (Tony's request, 2026-10-31): design note

After step 5, before step 7 (CoCo). Read-only: it never opens a store for writing, never writes into a store or a
source folder, and adds no dependency (`scipy.io.savemat` and the standard `csv` module are already there; HDF5 only
if Tony asks). The format page is [hlb-format.md](hlb-format.md).

## API

- `helab.utils.hlb.read(path) -> (header, arrays)`: reads and checks a file (`unpack` of its bytes). CoCo wrote
  `helab.hlb.read`. **Question:** is a top-level `helab/hlb.py` alias wanted, or is `helab.utils.hlb` fine?
- `helab.convert.raw_layer.columns(layer, bin_time=25e-12) -> dict`: a raw layer's export columns: `channel` (int8),
  `time_bins` (absolute, int64; float64 for `f64-1`) and `time_s` (float64), in the layer's stored order; plus the
  facts. It is the one place that undoes the deltas.

## CLI: `helab cache …`

A new `helab/cache_cli.py` (like `convert_cli.py`), dispatched by **one line in `helab/main.py`** beside `convert`'s
(`if sys.argv[1] == "cache": …`, before anything starts Qt). **To ask CoCo before touching `main.py`.**

```
helab cache dump FILE.hlb                         # the header, pretty JSON (arrays: name, dtype, shape, bytes)
helab cache export FILE.hlb [--to npz|mat|csv] [--out PATH] [--bin-time SECONDS]
helab cache export --folder FOLDER [--to …] [--out DIR] # every raw layer the store holds for FOLDER
```

- `--to` defaults to `npz`. `npz`: `numpy.savez_compressed` of the columns plus `header` (JSON text). `mat`:
  `scipy.io.savemat` (v5, `do_compression=True`), the same names. `csv`: `channel,time_bins,time_s` with a header
  row, one file per shot.
- `--out` defaults to beside the input for a file, and to `./helab-export-<folder name>/` for `--folder`. It never
  writes into the store or the source folder, and never replaces a file unless `--force`.
- `--folder`: the folder's store-v4 rows, found through its data root as the app keys it, with the store opened
  **read only** (a `mode=ro` connection, like `LegacyStore`), so it works beside a running HeLab and writes nothing.
  Each shot's `.hlb` is exported to `d<N>.<ext>`. Without a store-v4 (the switch off), it says there is nothing to
  export. store-v3 has no raw layers.
- Exit codes: 0 done, 1 nothing to export, 2 a file is damaged or of a newer format (named).

## Tests

A round trip per format (npz, mat, csv) on the case files' layers; damaged and newer-format files refused with
exit code 2; `--folder` against a temp store-v4 holding two shots, with the store's files hashed before and after
(byte-identical) and the I/O trace showing no write under the store or source folder; never replaces without
`--force`; the sample code on the format page run as a test (the "without HeLab" reader against a written file).
