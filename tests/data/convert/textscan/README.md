# textscan probes (cross-checker)

Raw-reader inputs and what MATLAB R2025b's `tdc_importer` textscan (`%f64%f64`, `Delimiter ','`,
`ReturnOnError`) reads from them. Each folder: the inputs, `list.txt`, and `matlab.txt` (one line
per input: name, row count, then the rows' values as `%.17g`), written by `textscan_dump.m` (run
from this folder with the folder name substituted for `fuzzts/`).

- `ts/`: the first 24 hand-made inputs (walkthrough §1).
- `ts2/`, `ts3/`: the end-of-line probes behind finding F1 in `../handoff.md`.
- `fuzzts/`: 400 random malformed inputs (half one corrupted line in a valid file, half token
  soup). The port's `parse_raw` matched 395; the 5 others are all F1.
