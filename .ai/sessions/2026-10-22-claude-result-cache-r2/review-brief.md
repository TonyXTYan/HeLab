# Review brief: Result Cache R2 (Codex Reviewer, Gauge)

Review `agent/result-cache-r2` at **`6906d96`** against base **`c3d4b50`** (`git diff c3d4b50...6906d96`).
Read `AGENTS.md` (Caching, Data roots, Responsive filesystem I/O, Script system),
`roadmaps/agent-workflow.md`, `roadmaps/result-caching.md`, the worker's `brief.md` (objectives 1–7;
the "Follow-up 1" section is work still to come, not to review), `notes.md` and `handoff.md` in this
folder.

**Where to work:** the worker (Cellar) keeps editing the floor's own checkout, so review and test in
the detached worktree CoCo made at that commit: `.ai/temp/review-results/` under the floor root (its
`venv` is a link to the floor's; `pytest.ini`'s `pythonpath = .` makes pytest import that worktree's
`helab`). From there: `source venv/bin/activate && source ../../local/floor-env.sh`, then
`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`, `mypy helab/ --strict`,
`mypy tests --strict`, `pyright helab tests`. Don't edit, commit or push anything; don't launch the GUI.

**Look hardest at:**
- Store rules: only helpers open the store (the GUI never does); `_migrate` adds the tables to older
  and concurrent stores once under the write lock; read-only stores read as empty; reads answer
  found / missing / error and an error is never "nothing saved".
- Save guards and epochs: a Clear cached analysis (root or all) or a purge racing a running save
  can't bring results back; root Clear cached data and Clear all leave results; `removed` resets
  exactly what it names in RAM; retired result files are swept, never deleted at once.
- Budget: results counted in live usage once (files and rows), the save's budget check in its
  transaction, `budget_set_at`; the 80 % pause sees results; 50 MiB notice once per save.
- Reuse correctness: `reuse_key` exactness (data fingerprints, script version/hash, parameters,
  constants, `found["reuse"]`, mask, environment); nothing reused across folders or roots; the
  outdated path never presents an outdated result as current; Live reruns never save or look up.
- Codec safety (`helab/analysis/result_codec.py`): no pickle, `allow_pickle=False`, malformed files
  fail cleanly; Correlations' and Release time's pack/unpack round-trip draws the same.
- I/O lanes: lookups and saves on the local lane, never waiting on foreground/background source I/O;
  helpers' events typed in `io_ops/events.py`; slots held until exit confirmed.
- Mixed versions: an older HeLab opening the migrated store (doesn't count results in its budget,
  never clears them) — say whether anything breaks.
- Tests that prove it, and doc changes the handoff should propose but doesn't.

**Report** to CoCo with `maestri ask "CoCo" "<findings>"`: most severe first, each with file:line,
what goes wrong and how you know; then the checks you ran with results (every RERUN with its
reason). Say plainly if you found no blocker.
