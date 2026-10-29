# Runner tools: notes (Worker, Claude Opus 5.5, 2026-10-30)

## Plan (sent to CoCo before building)

### 1. Milestone log lines

**Form** (one INFO line, logger `helab.milestone`, in HeLab's log file
`<app folder>/logs/helab-<pid>.log`, Help › Show log folder):

```
2026-10-30 10:00:00,123 INFO [4242 MainThread] helab.milestone: MILESTONE load_done folder="/data/2026 run" shots=120 events=4510233 seconds=12.403 source=folder live=false
```

- `MILESTONE <event>` then `key=value` pairs in a fixed order per event. Values: integers as is,
  floats with 3 decimals, booleans `true`/`false`, strings bare when they are `[A-Za-z0-9_.:/+-]+`
  and JSON-quoted otherwise (spaces, quotes, `=`, non-ASCII kept).
- One writer, `app_log.milestone(event, **fields)`, and one reader, `app_log.parse_milestone(line)`
  (for tests and runners), so the form can't drift. `logging` only: memory, no waits.
- No new kinds of data in the log: the folder path is already written by the existing lines
  (`Live on %s`, `Folder cache %s`, `Live auto-convert stopped for %s`); no file names, no
  parameter values.

**Events and sites** (one line each):

| Event | Site | Fields |
|---|---|---|
| `load_done` | `FolderCache` on a `loaded` it accepts (where `Dataset` is made) | `folder shots events seconds source live` (`source`: `cache` a cached read, `folder` a load that read TXY, `check` a load that read none) |
| `plot_done` | `AnalysisRunner._finished` (worker thread; `logging` is thread-safe) | `script version action plot job seconds state` (`state`: `ok`/`failed`/`cancelled`) |
| `convert_done` | `explorer_live._convert_event` on `convert_summary`; `convert_cli._Log` on `convert_summary` (after TXY Index lands) | `folder by converted failed waiting no_hit output seconds` (`by`: `live`/`cli`) |

### 2. The dev `.app` stub

`dev/dev_app.py` (standard library only; no helab import): writes `.ai/local/HeLab-dev.app`
(gitignored) with an `Info.plist` (`CFBundleIdentifier au.edu.anu.he-bec-lab.dev`, name
"HeLab dev", HeLab's icon, the checkout's path in `HeLabCheckout` and the Get Info string) and
`Contents/MacOS/HeLab-dev`, a shell script that `cd`s to the checkout and
`exec`s `venv/bin/python -m helab "$@"`. `exec` keeps the PID LaunchServices launched, so the
process keeps the bundle's identity (probe, 2026-10-30: `lsappinfo` gave the bundle ID for the
python PID, and CGWindowList named the window's owner after the bundle).
