# Cross-checker handoff: TXY converter stage 1 (Lens, 2026-10-29)

Checked the builder's port at `d14f0cb` (`helab/convert/` unchanged since `9268515`). What I did
and the evidence: [notes.md](notes.md). The MATLAB reading: [matlab-walkthrough.md](matlab-walkthrough.md).
The cases: [cases/](cases/README.md). Reader probes: [probes/](probes/README.md).

## Verdict

The port reproduces MATLAB byte for byte on everything MATLAB has been shown: all 39 cases × 2
variants, all 309 sample shots for `matlab-2019` (303 identical, 6 proved reference faults, 0
unexplained), all 152 odd-position shots for `matlab-2023-lab-edit` against my own MATLAB run,
and 10,000 fuzzed raw files × 2 variants against my independent oracle. Every quirk in the
walkthrough's checklist (§9) is in `backends/reference.py` with the right MATLAB line.
**No finding changes the output of any real raw file.** Five low or cosmetic findings below; none
blocks stage 1 in my view.

## Results

`matlab-2019` against the sample set's references (`dev/txy/check_samples.py --positions all`;
odd positions run first: 152 shots, 149 identical, 3 proved):

| Set | Shots | Identical | cut | variant | empty | Differ |
|---|---|---|---|---|---|---|
| 2019-halos-old-plates | 43 | 42 | 1 | 0 | 0 | 0 |
| 2020-halos-weak-trap | 42 | 41 | 0 | 0 | 1 | 0 |
| 2022-07-old-plates-he3he4 | 42 | 40 | 0 | 2 | 0 | 0 |
| 2022-07-old-plates-large-he3 | 43 | 43 | 0 | 0 | 0 | 0 |
| 2022-11-ghost-counts-mcp | 10 | 9 | 0 | 0 | 1 | 0 |
| 2023-02-new-plates-he3he4 | 43 | 42 | 0 | 0 | 1 | 0 |
| 2023-03-momentum-bells | 43 | 43 | 0 | 0 | 0 | 0 |
| 2024-11-rt-low-occupancy | 43 | 43 | 0 | 0 | 0 | 0 |
| **all** | **309** | **303** | **1** | **2** | **3** | **0** |

`matlab-2023-lab-edit` against MATLAB's own output (my MATLAB R2025b run of the 2023 wrapper on
copies of every odd-position shot; the builder ran the even ones): 152/152 identical (21 per set,
5 for 2022-11), 614,136 hits, two of them 0-byte files.

Cases: 78/78. Converter tests: 173 passed, no reruns; strict mypy and pyright clean on
`helab/convert` and `tests/test_convert_*`.

**The six reference faults** (`dev/txy/reference_exceptions.py`), each confirmed by me with
MATLAB, not only with the port: d3667 cut (only K = 40,956…40,966 lines reproduce it); 2022-07
he3he4 d2 and d3, a third MATLAB variant (2019 + a **2.0 µs** x1 `uniquetol` cut, T with
`T_sum` 3200; 1/1.5/2.5/3 µs don't match); 2020-halos d400, 2022-11 d5, 2023-02 d187 empty (no
hit; MATLAB 2019 writes no file, the 2023 wrapper a 0-byte file equal to each reference).
d400's 0-byte TXY dates 2 s after its raw (2020-08-06 18:19:42 → :44), so the lab's live
converter in 2020 was not the pinned `dld_raw_to_txy_counts`, which writes none.

## Findings, most severe first

All low; F1–F2 are behaviour, F3 a report figure, F4–F5 wording.

**F1 (low) `helab/convert/raw.py:11`, `:42`, `:100–104`: line endings aren't read as textscan
reads them.** textscan takes the end of line from the first non-blank line: after a CRLF line,
`\r\n`, `\n` and `\r` all end lines (the port does this); after an LF line, a later `\r` stops
the read (one at the very end of the file doesn't); after a CR line, a later `\n` stops it. The
port treats all three as line ends everywhere, and the fast path `_STRICT` (`\r?\n`) accepts
mixed LF/CRLF files. Example: `1,10\n2,20\r\n3,30\n` → MATLAB 2 rows, port 3 (fast path).
Evidence: [probes/ts2](probes/ts2), [probes/ts3](probes/ts3) (inputs and MATLAB's rows); all 5
of the 400 MATLAB-judged fuzz inputs the port missed are this. **Impact:** none on TDC files,
which are uniformly CRLF; only a mixed-ending file differs. Fix: either follow the rule (decide
the line ending from the first non-blank line; in LF mode `\r` before EOF is a stop, in CR mode
`\n` is), with ts2/ts3 as tests, or note it as a known difference and have stage 4's
done-writing check refuse files whose line endings aren't all CRLF (A~1).

**F2 (low) `helab/convert/txy.py:50`: TXY files are written with mode 0600.**
`tempfile.mkstemp` creates the file owner-only and `os.replace` keeps that, so every TXY HeLab
writes is `-rw-------` (checked: `0o600`; MATLAB's `fopen` gives `0o644` under the usual umask).
Harmless in HeLab's temp folder; wrong once stage 4 writes beside the raw files (Q9.7) in a
folder other lab accounts or an SMB share read. Fix: `os.chmod(temporary, 0o666 & ~umask)`
before the rename (read the umask once at import), with a test.

**F3 (low) `x2-handling.md`, the "Retry would match" column overstates the gain by ~15 %.** All
other counts agree with mine exactly (hits, x2 ambiguous 49,040, "of which x2 ambiguous" 10,119,
y ambiguous 2,432). Simulating the whole shot with the retry on (a recovered hit takes its
pulses, later x1 rows then can't), the net gain is **+4,255 hits (0.29 %)**, not 4,944 (0.33 %):
4,648 hits are recovered and 393 later MATLAB hits are lost to them. Per set: 2019 halos +491
(0.19 %), 2020 halos +164 (0.13 %), 2022-07 he3he4 +1,192 (0.41 %), large He3 +2,402 (0.67 %),
2022-11 +2, 2023-02 +3, 2023-03 +1, 2024-11 0. Trying every x2 in the window, not only the
second, adds just 34 more (+4,289). So the readings should say "0.1–0.7 %" and "retrying
beyond the second candidate barely matters". Figures: [x2-measure.json](x2-measure.json),
[tools/x2_measure.py](tools/x2_measure.py). The readings otherwise stand.

**F4 (cosmetic) `helab/convert/profile.py:34`:** "which rounds differently from x1 − x2" isn't
so for real data: with integer bin times below 2^52, (x1 − tx) − (x2 − tx) is exactly x1 − x2.
Suggest "computed in MATLAB's order (the same value for integer times below 2^52)".

**F5 (cosmetic) `helab/convert/check.py:41–46`:** a side that has ended is reported as `''`
(the empty piece after the last newline), not `None` as the docstring says; and a reference
without its final newline shows as "line N+1: ours '', reference None". E.g. ours 3 lines,
reference the first 2: "first difference at line 3: ours 'c', reference ''". Suggest dropping
the trailing empty piece before comparing and saying "(ended)" / "(no final newline)".

## For stage 2 (not stage-1 findings)

The `within-shot` parallelism (cut a shot at pulse gaps, reconstruct pieces in parallel) stays
byte-identical only if it keeps what is global in MATLAB: `t_zero` and the skipped first sorted
row (whole file); the phantom row, which depends on the **whole file's** N (`floor(N/4)`
prealloc) and on the total hit count, so pieces must not each make their own; the 2023 x1
dead time, whose `uniquetol` groups reach 20,000 bins, so a cut needs a gap over 20,000 bins
there (3,200 is enough for 2019's matching); and the final stable sort by T over all pieces in
generation order. Gaps must be counted in sorted rows too: the ±18-row window can't reach across
a time gap > 3,200 bins because of the `T_sum` skip, so that part is safe.

## Proposed doc changes (for the Coordinator)

- `.ai/architecture/converter.md` (new), from the walkthrough: the running path in brief, the
  quirk list (walkthrough §9, including the phantom row and the two wrappers' empty-result
  behaviour), the reader's textscan rules (and F1's resolution), the reference-fault classes
  (cut / variant / empty) and how `check_samples.py` proves them, and the `.gitattributes`
  rule for byte-exact fixtures.
- `roadmaps/txy-converter.md`, stage 1: done when the Reviewer agrees; "byte-identical on every
  sample shot" reads "303 of 309, the other 6 proved reference faults".
- `roadmaps/txy-converter.md`, What the MATLAB converter does: a third variant existed on the lab
  PC around 2023-02 (2019 + 2 µs x1 dead time; it re-converted two 2022-07 shots on 2023-02-08),
  and the 2020 live converter wrote 0-byte TXY for empty shots.
- `known-issues.md`, if not fixed in this stage: F1 and F2.

## Provisional items

- **Q~1 (Tony): a shot with no hits, no TXY or an empty one?** `matlab-2019` writes none (the
  pinned wrapper); the lab's files show 0-byte TXYs from 2020, 2022-11 and 2023-02 (other
  wrappers). Options: (a) none, as the pin (Live must then remember "converted, no hits" so it
  doesn't retry); (b) a 0-byte TXY for HeLab's own output (`d_txy_helab_<N>.txy`), keeping
  `matlab-2019`'s none only for comparisons. Proposed: (b): an empty file says "converted"
  without extra state, and HeLab's files have their own name anyway.
- **Q~2 (Tony): the 2 µs variant.** Who ran it and why is unknown (2023-02-08, two 2022-07
  shots). Proposed: no built-in profile; it stays an exception in `reference_exceptions.py`, and
  `matlab-2019` plus `dead_time_x1 = 2e-6` reproduces it when needed.
- **A~1:** resolve F1: make `parse_raw` follow textscan's line-ending rule with
  `probes/ts2` and `probes/ts3` as tests, or have stage 4's done-writing check refuse raw files
  whose line endings aren't all CRLF (and list the difference in converter.md).
- **A~2:** fix F2 (TXY file mode) before stage 4 writes beside raw files.
- **A~3:** stage 2's within-shot split: the constraints above, with a test that a split
  conversion equals the whole one on `phantom_*` and `dead_time_x1` cases.
- No `M~` items: nothing here needs Tony at a screen or the lab.

## Round 2 (785f6dc, plus `dd6b314` and Forge's uncommitted `txy.py` seen in the tree)

Re-run on 785f6dc: fuzz 10,000 raw files × 2 variants, port vs oracle: 0 differences; cases
78/78; all 449 round-1 probes: 449/449; samples (`--positions all`): 303 identical + 6 proved, 0
unexplained, d400 listed and proved; converter tests 675 passed, 2 skipped, no reruns; strict
mypy and pyright clean. F2: TXY now `0o644`. F3: `x2-handling.md` and `dev/txy/x2_retry.py` give
my net figures (+4,255, +4,289); their gross/lost split (4,825 / 570) counts differently from mine
(4,648 hits whose final x2 was a retry / 393 lost) but nets the same. F4, F5: done as suggested.
`check.py`'s `ReferenceFault` / `prove_fault` and the `(ended)` / `(no final newline)` marks read
right. The uncommitted `write_atomic` (`os.open(…, O_WRONLY|O_CREAT|O_EXCL|O_BINARY, 0o666)`, so
the kernel applies the umask, instead of `os.umask(0)` at import) is right, `O_BINARY` included;
I'll re-run it when committed.

**R2-1 (low, open) `helab/convert/raw.py:94–96`: the line-ending rule is still wrong for files
that begin with blank lines.** F1's fix was fitted to probes without leading line endings. A
fresh MATLAB-judged fuzz shows the port missing **34 of 500** mixed-ending inputs
([probes/fuzzeol](probes/fuzzeol)), **146 of 400** with leading runs
([probes/fuzzlead](probes/fuzzlead)) and 7 of 18 targeted probes ([probes/ts4](probes/ts4)).
Two things differ from MATLAB:

1. **Detection skips only the `\n` characters at the very start of the file**, not spaces,
   tabs or `\r`; the first `\r`/`\n` run after them then sets the mode with the port's
   mapping (`\r+\n` → all three, `\n…` → `\n`, lone `\r+` → `\r`). So `\r0,10\r\n2,20\r\n` is
   CR mode (MATLAB: 1 row; port: 2), `\n\r0,10\r\n` is CR mode (MATLAB: none), and
   `␠\n0,10\r\n2,20\r\n` is LF mode (MATLAB: 1 row).
2. **Parsing starts at byte 0**, under that mode. The skipped leading `\n`s are then line ends
   only if the mode accepts `\n`; in CR mode they stop the read at once
   (`\n0,10\r\r3,30\n` → MATLAB no rows, port 2).

The fix, which I checked in a scratch copy of `_parse_textscan` (the port isn't edited):

```python
pos, end = 0, len(data)
first = _LINE_END.search(data, len(data) - len(data.lstrip(b"\n")))
```

`_LEADING` is then unused. With it, all **1,367** MATLAB-judged inputs agree (ts 24, ts2 17, ts3 8,
fuzzts 400, ts4 18, fuzzeol 500, fuzzlead 400, the last a fresh set made after the rule was
fixed). Suggest adding ts4, fuzzeol and fuzzlead to `tests/data/convert/textscan/`. Still no
effect on TDC files (uniform CRLF, no leading blank lines; the fast path takes them).

Open findings after round 2: **R2-1** only.

## Round 3 (09a0711): no open findings

R2-1 is fixed exactly as proposed (`raw.py:94–98`); `write_atomic` now creates the temporary
with `os.open(…, O_WRONLY|O_CREAT|O_EXCL|O_BINARY, 0o666)`. Re-run on 09a0711: fuzz 10,000 raw
files × 2 variants, port vs oracle, 0 differences; cases 78/78; all **1,367** MATLAB-judged
reader probes (ts 24, ts2 17, ts3 8, ts4 18, fuzzts 400, fuzzeol 500, fuzzlead 400): 0
mismatches; samples `matlab-2019` all 309 = 303 identical + 6 proved, 0 unexplained;
`matlab-2023-lab-edit` 152/152 against my MATLAB run; TXY written `0o644`, LF only, `-0` kept,
overwrite leaves no `.partial`, and 16 concurrent writers to one target leave one writer's whole
file and nothing else; converter tests 1,597 passed, 2 skipped, no reruns; strict mypy and
pyright clean on `helab/convert` and `tests/test_convert_*`.

A wording nit, not a finding: `raw.py:11` still opens with "The first non-blank line's ending
sets…" before the exact rule that follows; "The first line ending (after any `\n` at the very
start) sets…" would match it.

**Open findings: none.**
