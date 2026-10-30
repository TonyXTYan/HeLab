# Runner tools: notes (Worker Kestrel, Claude Opus 5.5, 2026-10-30)

The plan went to CoCo before building; CoCo answered "Plan OK", with `no_hit` as this run's
growth of `AutoConvert.no_hits` (no session totals beside per-run counts), no `events.py`
change, the CLI's counter lines allowed after TXY Index lands, and the screenshot left as M~1.

## 1. Milestone log lines

**Form.** One INFO line on the logger `helab.milestone`, so in HeLab's log file
(`<app folder>/logs/helab-<pid>.log`, Help › Show log folder; macOS
`~/Library/Caches/HeLab/logs/`, a floor's under `~/Library/Caches/HeLab/floors/<floor>/app/logs/`):

```
2026-10-30 10:00:00,123 INFO [4242 MainThread] helab.milestone: MILESTONE load_done folder="/data/2026 run" shots=120 events=4510233 seconds=12.403 source=folder live=false
```

- `MILESTONE <event>`, then `key=value` in a fixed order per event. Integers bare, floats to 3
  decimals, `true`/`false`/`null` (a NaN is `null`), strings bare when plain (`[A-Za-z0-9_.:/+-]+`)
  and not readable as another type, JSON-quoted otherwise.
- `app_log.milestone(event, **fields)` writes every line; `app_log.parse_milestone(line)` reads one
  back, typed (runners and tests). A runner can also just `grep 'MILESTONE load_done'`.
- `logging` only: memory, no waits, any thread (plot_done is on the worker thread).
- Privacy (block 29): the only path is the folder, which the log already writes (`Live on %s`,
  `Folder cache %s`, `Live auto-convert stopped for %s`, `helab convert`'s plan line). No file
  names, parameter values or data.

| Event | Site | Fields |
|---|---|---|
| `load_done` | `FolderCache._job_event`, where an accepted `loaded` becomes a `Dataset` | `folder shots events seconds source live`; `source`: `cache` (a cached read), `folder` (a load that read TXY files), `check` (a load that read none: checked against the folder, data from memory or the cache); `seconds` from the job's creation |
| `plot_done` | `AnalysisRunner._finished` (every job end) | `script version action plot job seconds state`; `plot` the plot instance (`AnalysisContext.owner`), `state` `ok`/`failed`/`cancelled` |
| `convert_done` | `explorer_live._convert_event` on `convert_summary` (`by=live`); `convert_cli._Log` (`by=cli`) | `folder by converted no_hit unconvertible waiting kept output seconds` |

`convert_done`'s counts are all the run's: `converted` and `no_hit` (0 hits, a 0-byte TXY) are the
shots this run converted; `unconvertible`, `waiting` and `kept` are the folder's files as this run
left them (the summary's lists, which carry files unchanged since an earlier run). In the GUI,
`no_hit` is the growth of `AutoConvert.no_hits` since the last line (`no_hits_logged`).

**A run that changed nothing logs no `convert_done`** (my call, after CoCo's OK of the plan): Live
auto-convert runs a conversion every Live interval (3 s by default), so a line per run would be
about 1,200 an hour and rotate useful lines out of a 1 MB log. A run logs its line when it is the
first (since auto-convert went on, or since `helab convert` started), converted shots, found
no-hit ones, or left the unconvertible, waiting or kept counts different from the last line
(`AutoConvert.logged_counts`; in `helab convert`, `_Log`'s own). So the line after a run that
converts a runner's shots is always there, and one that only repeats the last is not.

Not logged: a failed or cancelled load (the existing warning lines say so); a saved result read
back from the disk cache (it doesn't go through the runner).

## 2. The dev `.app` stub

`dev/dev_app.py` (standard library only, no helab import, macOS only) writes
`.ai/local/HeLab-dev.app` (gitignored) and registers it with `lsregister -f`:

- `Info.plist`: `CFBundleIdentifier au.edu.anu.he-bec-lab.dev`, name `HeLab-dev`, HeLab's icon,
  the checkout's version, `HeLabCheckout` (the checkout's path, also in Get Info) and `HeLabEnvFile`.
- `Contents/MacOS/HeLab-dev`: a `sh` script that sources `--env-file` (if given), drops `-psn_…`
  arguments, `cd`s to the checkout and `exec`s `venv/bin/python -m helab "$@"`. Without the venv it
  says so on stderr and in an alert, and exits 1.

**Why `exec` works.** LaunchServices registers the PID it launched; `exec` keeps that PID, so
the python process is the bundle's (lsappinfo: `executable path=…/venv/bin/python`,
`originalExecutablePath=…/HeLab-dev.app/Contents/MacOS/HeLab-dev`, same pid).

**The name.** LaunchServices shows the bundle's file name (`LSDisplayName`, window owners), not
`CFBundleName`: a first build named "HeLab dev" in Info.plist still showed as "HeLab-dev". So the
name, the file and Info.plist all say `HeLab-dev` (`HeLab-dev-<tag>` with `--tag`).

### Evidence (macOS 26, Darwin 25.6, this floor, 2026-10-30)

`python dev/dev_app.py --env-file .ai/local/floor-env.sh`, then
`open .ai/local/HeLab-dev.app --args --probe-arg "two words"`, 12 s later:

```
$ lsappinfo info -app au.edu.anu.he-bec-lab.dev
"HeLab-dev" ASN:0x0-0x1b4eb4d:
    bundleID="au.edu.anu.he-bec-lab.dev"
    bundle path="~/GitHub-Local/.maestri/floors/HeLab--agentrunner-tools/.ai/local/HeLab-dev.app"
    executable path="~/GitHub-Local/.maestri/floors/HeLab--agentrunner-tools/venv/bin/python"
    pid = 88805 type="Foreground" flavor=2 Version="0.0.6a1" fileType="APPL" creator="????" Arch=ARM64
    originalExecutablePath="~/…/HeLab-dev.app/Contents/MacOS/HeLab-dev" originalPid=88805
    launch to checkin time: 1.74795 seconds
$ osascript -e 'application id "au.edu.anu.he-bec-lab.dev" is running'
true
$ osascript -e 'application id "au.edu.anu.he-bec-lab" is running'
false
$ ps -o pid,args -p 88805
88805 ~/…/venv/bin/python -m helab --probe-arg two words
$ windows 88805        # a 10-line Swift CGWindowListCopyWindowInfo listing (scratchpad, not committed)
id=26601 owner=HeLab-dev layer=0 onscreen=1 bounds=1600x928+723+383
```

The log went to the floor's app folder (`~/Library/Caches/HeLab/floors/Runner Tools/app/logs/`),
so `--env-file` reached HeLab. `kill -TERM` ended it in 2 s, helpers included.

**Arguments.** `open … --args A B` reaches `python -m helab A B` (above). HeLab ignores arguments
it doesn't know today (they go to `QApplication`), so `--geometry` does nothing until the Smoke
ready floor adds it; then `open .ai/local/HeLab-dev.app --args --geometry 1600x928+0+39`.

**While it runs.** A second `open … --args --second` only brought it forward: the running process
kept `--first`, and `--second` was dropped. `open -n … --args --third` started a second process
with the same ID; `lsappinfo info -app au.edu.anu.he-bec-lab.dev` then printed nothing (two
matches), so a runner quits the first one (and checks its PID is gone) before opening again.

**Two checkouts.** Each stub runs the checkout it was built in (`HeLabCheckout`, Get Info). With
the default ID, two checkouts' stubs answer for the same ID (LaunchServices picks one for
`open -b`), so the second gets `--tag <name>`: `au.edu.anu.he-bec-lab.dev.<name>`, `HeLab-dev-<name>.app`.

**Environment.** `open` starts the app with launchd's environment, not the shell's. A floor
passes `--env-file .ai/local/floor-env.sh`, so the stub never uses Tony's settings and cache;
`open --env NAME=VALUE` works too.

**Not shown here: the screenshot.** This shell has no Screen Recording grant
(`screencapture -l <id>` and `-R` both: "could not create image"), and `osascript` through System
Events timed out (Automation consent), so the window was shown by CGWindowList (on screen,
1600×928, owner HeLab-dev), not an image. M~1 asks for a computer-use screenshot.

## Probes (scratchpad, not committed)

- A `Probe.app` with a `sh` executable that `exec`s the venv's python on a PyQt6 label: lsappinfo
  had the bundle ID on the python PID; the window owner was "Probe".
- `osascript -e 'tell application "System Events" …'` timed out after 2 minutes (no Automation
  grant for this terminal); `application id "…" is running` needs no grant.
