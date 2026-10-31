# HeLab's `.hlb` files

HeLab's caching v2 (store-v4) keeps its binary data in `.hlb` files. This page describes the format and how to
read one with or without HeLab, from the command line, and from MATLAB. Store-v4 is built behind a switch that
stays off until caching v2's stage 2 ([plan](../roadmaps/caching-v2.md)), so today's HeLab writes no `.hlb`
files unless that switch is on. HeLab's code: `helab.utils.hlb.read`, `helab.convert.raw_layer.columns`, and
`helab cache dump|export` (`helab/cache_cli.py`). The "without HeLab" sample below runs as a test
(`tests/test_cache_cli.py`), checked against a file HeLab wrote. Written 2026-10-31 (caching v2 stage 1; Q42.5, Q44.2).

## What a `.hlb` file is

HeLab's caching v2 (store-v4) keeps binary data in `.hlb` files: named NumPy arrays, compressed, with a JSON header
that says what they are and who made them. No Python pickle anywhere, so any language can read one. Today the only
kind is a **raw layer**: one raw TDC file `d<N>.txt` parsed into its pulses (`store-v4/raw/<uuid>.hlb`). Stage 2 adds
TXY layers (`kind` `txy`) in the same container.

## Byte layout (format 1)

| Offset | Size | Field |
|---|---|---|
| 0 | 8 | magic `89 48 4C 42 0D 0A 1A 0A` (`\x89HLB\r\n\x1a\n`; a text-mode copy or a cut file fails it) |
| 8 | 4 | header length `L`, unsigned little-endian (at most 16 MiB) |
| 12 | 4 | CRC32 (zlib's) of the header's bytes, unsigned little-endian |
| 16 | `L` | header: JSON, UTF-8 |
| 16 + `L` | to the end | the arrays' compressed chunks, back to back, in the order the header lists them |

The chunks tile the rest of the file exactly: no gap, no overlap, nothing after the last.

## The header

```json
{
  "format": 1,
  "kind": "raw",
  "maker": {"maker": "<session id>", "record": {"helab_version": "…", "commit": "…", "hostname": "…", "…": "…"}},
  "meta": {"encoding": "i8-i64d-1", "parser": 1, "facts": {"rows": 41092, "t_zero": "13656646605557.0", "…": "…"},
           "name": "d1.txt"},
  "arrays": [
    {"name": "channel", "dtype": "|i1", "shape": [41092],
     "codec": {"name": "blosc", "cname": "zstd", "clevel": 9, "shuffle": "byte", "typesize": 1},
     "chunks": [{"offset": 0, "length": 12345, "size": 41092, "crc32": 305419896}]},
    {"name": "time", "dtype": "<i8", "shape": [41092], "codec": {"…": "…"}, "chunks": [{"…": "…"}]}
  ]
}
```

- `format`: this layout's version. A reader refuses a higher one; it never rewrites a file.
- `kind`: `raw` (a raw layer), later `txy`.
- `maker`: which HeLab session made the file (Q28.4): its id, and its record with HeLab's version and commit, the
  machine's random id, **its hostname**, and Python, NumPy, SciPy and blosc versions. A file shared off the machine
  carries the hostname.
- `meta`: the kind's own fields (below).
- `arrays`: each one's `name`; `dtype` in NumPy's spelling with explicit byte order (`|i1`, `|u1`, `<i8`, `<f8`, the
  only ones read today); `shape`; `codec`; and `chunks`. In each chunk, `offset` counts from the end of the header,
  `length` is its compressed bytes, `size` its uncompressed bytes (at most 64 MiB, cut at element boundaries) and
  `crc32` is zlib's CRC32 of its compressed bytes.
- **Codec** `blosc`: each chunk is one python-blosc (Blosc 1) frame, decompressed with `blosc.decompress`.
  `cname` and `clevel` are as written (raw layers: zstd 9, Q22.7). `shuffle` `byte` is Blosc's byte shuffle by
  `typesize`, undone by the decompressor itself.

## Raw layers (`kind` `raw`)

`meta.encoding` says which arrays the file holds:

- **`i8-i64d-1`** (the TDC's own files): `channel` (`|i1`) and `time` (`<i8`). The time is stored as row 0's time,
  then each row's difference from the one before, so `numpy.cumsum(time)` gives the absolute TDC times. **Row order:**
  the file's first row (the trigger, MATLAB's `t_zero`) comes first, then every other row sorted by time, with ties
  in file order. Every converter backend reads the pulses in this order and gives byte-identical TXY.
- **`f64-1`** (any other file: other line endings, NaN fields, decimals, …): `channels` and `times` (`<f8`), exactly
  as HeLab's reader parses the text, **in file order**, NaN where a field was empty.

Times are TDC bins. HeLab's profiles use **25 ps** (`bin_time` 25e-12 s), so seconds = bins × 25e-12.

`meta.facts` holds what HeLab's done-writing checks read from the text: `rows`, `t_zero` (as text; `"nan"` for an
empty file), `first_channel`, `blank`, `final_newline`, `line_endings` (`crlf`, `lf`, `cr`, `mixed`, `none`) and
`reader` (`strict` or `general`). `meta.parser` is HeLab's parser version (1).

## The format rule

An **additive** change keeps `format` 1: a new header field, a new `meta` field, a new array, a new `kind`, a new
encoding name, or a new codec or dtype. Readers ignore fields they don't know, and refuse an array whose dtype or
codec they don't know (an error, never a silent guess). Only a change to this byte layout, or to what an existing
field means, raises `format`. An older HeLab meeting a newer `format` refuses the file and **never rewrites, moves
or deletes it**.

## Reading one

### Python, with HeLab

```python
from helab.utils import hlb
header, arrays = hlb.read("d1.hlb")               # every part checked; hlb.HlbError if not
from helab.convert import raw_layer
layer, header = raw_layer.from_hlb(open("d1.hlb", "rb").read())
columns = raw_layer.columns(layer)                # channel, time_bins (absolute), time_s
pulses = raw_layer.decode(layer)                  # or: .channels, .times (float64, TDC bins), as the converter reads them
```

### Python, without HeLab (NumPy and python-blosc only)

```python
import json, struct, zlib
import blosc, numpy as np

def read_hlb(path):
    data = open(path, "rb").read()
    if data[:8] != b"\x89HLB\r\n\x1a\n":
        raise ValueError("not a .hlb file")
    length, crc = struct.unpack_from("<II", data, 8)
    header_bytes = data[16:16 + length]
    if zlib.crc32(header_bytes) != crc:
        raise ValueError("header damaged")
    header = json.loads(header_bytes)
    base, arrays = 16 + length, {}
    for entry in header["arrays"]:
        pieces = []
        for chunk in entry["chunks"]:
            packed = data[base + chunk["offset"]:base + chunk["offset"] + chunk["length"]]
            if zlib.crc32(packed) != chunk["crc32"]:
                raise ValueError(entry["name"] + ": chunk damaged")
            pieces.append(blosc.decompress(packed))
        arrays[entry["name"]] = np.frombuffer(b"".join(pieces), dtype=entry["dtype"]).reshape(entry["shape"])
    return header, arrays

header, arrays = read_hlb("d1.hlb")
if header["meta"]["encoding"] == "i8-i64d-1":
    channel, bins = arrays["channel"], np.cumsum(arrays["time"])
else:
    channel, bins = arrays["channels"], arrays["times"]
seconds = bins * 25e-12
```

*Checked* against a file HeLab wrote (`tests/data/convert/cases/basic/d1.txt`'s layer): the same channels and times
as `raw_layer.decode`.

### From the command line (read only)

```
helab cache dump d1.hlb                                   # the header as JSON (arrays without their chunk lists)
helab cache export d1.hlb --to npz|mat|csv [--out PATH]   # channel, time_bins, time_s, header
helab cache export --folder /data/2026-10-31/run --to mat # every raw layer store-v4 holds for that folder
```

A file's export goes to the current folder (`d1.npz`), a folder's to `./helab-export-<name>/d<N>.<ext>`; nothing is
replaced without `--force`, and nothing is ever written into a store. `--bin-time` changes the seconds per bin.

### MATLAB

MATLAB has no Blosc reader, so export the file first: `helab cache export d1.hlb --to mat` writes a `.mat` with
`channel` (int8), `time_bins` (absolute, int64), `time_s` (double) and `header` (the JSON text):

```matlab
s = load('d1.mat');
plot(s.time_s(s.channel == 5), '.');   % the trigger channel's pulses
info = jsondecode(s.header);
```
