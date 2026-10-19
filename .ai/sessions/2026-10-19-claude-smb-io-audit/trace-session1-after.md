# I/O trace summary: <out>.s1.trace.jsonl

## Phases

| Phase | Seconds | Helpers | Source ops | Ops/min | Listings | Stats | Reads | Tail/marker/icon | GUI-process |
|---|---|---|---|---|---|---|---|---|---|
| S1 startup | 2 | 9 | 18 | 540.4 | 2 | 7 | 0 (0.0 MB) | 9 | 0 |
| S1 idle 60 s, tree open | 60 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 expand 2026/10/18 and 19 | 2 | 9 | 36 | 964.3 | 8 | 18 | 0 (0.0 MB) | 10 | 0 |
| S1 select and load run_a (120 shots) | 1 | 3 | 604 | 25,093.0 | 2 | 482 | 120 (3.0 MB) | 0 | 0 |
| S1 select and load run_b (40 shots) | 1 | 2 | 204 | 9,169.3 | 2 | 162 | 40 (1.0 MB) | 0 | 0 |
| S1 reselect run_a within 10 s | 4 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 idle 15 s | 15 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 reselect run_b after 15 s (disk cached) | 1 | 1 | 6 | 322.5 | 0 | 6 | 0 (0.0 MB) | 0 | 0 |
| S1 second tab: RAM-only folder, load run_r | 2 | 7 | 611 | 17,711.6 | 4 | 485 | 120 (3.0 MB) | 2 | 0 |
| S1 tab switch 1 (to tab 1) after 15 s | 16 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 tab switch 2 (to tab 2) after 15 s | 16 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 tab switch 3 (to tab 1) after 15 s | 16 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 tab switch 4 (to tab 2) after 15 s | 17 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 toolbar Refresh | 2 | 11 | 48 | 1,252.0 | 10 | 22 | 0 (0.0 MB) | 16 | 0 |
| S1 right-click Retry / Refresh on run_b (shown) | 2 | 2 | 84 | 2,511.4 | 2 | 82 | 0 (0.0 MB) | 0 | 0 |
| S1 select and load run_live | 1 | 3 | 154 | 6,655.2 | 2 | 122 | 30 (0.8 MB) | 0 | 0 |
| S1 Live on, writer adds 12 shots every 4 s (1004 written over 7.5 s, 1009 pauses 4 s mid-file) | 60 | 30 | 286 | 286.5 | 17 | 204 | 10 (0.3 MB) | 55 | 0 |
| S1 Live on, writer done: 15 s to settle | 15 | 6 | 35 | 140.0 | 2 | 25 | 2 (0.1 MB) | 6 | 0 |
| S1 Live on, nothing new, 60 s | 60 | 20 | 29 | 29.0 | 1 | 25 | 0 (0.0 MB) | 3 | 0 |
| S1 Live off (saves new shots) | 2 | 1 | 46 | 1,373.2 | 1 | 42 | 0 (0.0 MB) | 3 | 0 |
| S1 load run_stall while its new shot 2001 stalls 8 s mid-file (selected 6.5 s in) | 9 | 2 | 59 | 380.7 | 2 | 46 | 11 (0.3 MB) | 0 | 0 |
| S1 simulated mount change (a listing reports another mount table), 30 s | 30 | 2 | 5 | 10.0 | 0 | 2 | 0 (0.0 MB) | 3 | 0 |
| S1 a listing reports the real mount table again, 15 s | 16 | 2 | 9 | 33.7 | 2 | 7 | 0 (0.0 MB) | 0 | 0 |
| S1 select a folder that can't be listed (permission), 20 s | 20 | 2 | 2 | 6.0 | 1 | 1 | 0 (0.0 MB) | 0 | 0 |
| S1 select a folder whose file read hangs (timeouts 3/4/5 s), until it fails | 14 | 4 | 128 | 539.6 | 4 | 105 | 19 (0.5 MB) | 0 | 0 |
| S1 idle 60 s at the end | 60 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 quit | 2 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 end | 0 | 0 | 0 | – | 0 | 0 | 0 (0.0 MB) | 0 | 0 |

## S1 startup (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| cache_admin | app | – | 2 | 60.0 |
| volumes_verify | app | – | 2 | 60.0 |
| resolve | tab1 | – | 1 | 30.0 |
| list | tab1 | – | 1 | 30.0 |
| details | tab1 | – | 1 | 30.0 |
| icons | tab1 | – | 1 | 30.0 |
| roots_verify | app | – | 1 | 30.0 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| icons | icon | folder icon | 3 | 90.1 | several (native lookup) |
| details | lstat | subfolder date | 2 | 60.0 | CREATE/QUERY_INFO (or cached) |
| resolve | stat | resolve | 1 | 30.0 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 30.0 | CREATE/QUERY_INFO (or cached) |
| list | marker_open | root discovery | 1 | 30.0 | CREATE (a missing one: CREATE fails) |
| list | marker_fstat | root discovery | 1 | 30.0 | QUERY_INFO (or cached) |
| list | marker_read | root discovery | 1 | 30.0 | READ + CLOSE |
| list | scandir | listing | 1 | 30.0 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | scandir | listing | 1 | 30.0 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 1 | 30.0 | CREATE/QUERY_INFO (or cached) |
| roots_verify | stat | roots_verify: root folder | 1 | 30.0 | CREATE/QUERY_INFO (or cached) |
| roots_verify | lstat | roots_verify: marker | 1 | 30.0 | CREATE/QUERY_INFO (or cached) |
| roots_verify | marker_open | root discovery | 1 | 30.0 | CREATE (a missing one: CREATE fails) |
| roots_verify | marker_fstat | root discovery | 1 | 30.0 | QUERY_INFO (or cached) |
| roots_verify | marker_read | root discovery | 1 | 30.0 | READ + CLOSE |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share | 3 |

## S1 expand 2026/10/18 and 19 (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | – | 4 | 107.1 |
| details | tab1 | – | 4 | 107.1 |
| icons | tab1 | – | 1 | 26.8 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| details | lstat | subfolder date | 10 | 267.9 | CREATE/QUERY_INFO (or cached) |
| icons | icon | folder icon | 10 | 267.9 | several (native lookup) |
| list | lstat | listing: marker | 4 | 107.1 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 4 | 107.1 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | scandir | listing | 4 | 107.1 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 4 | 107.1 | CREATE/QUERY_INFO (or cached) |

## S1 select and load run_a (120 shots) (1 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | – | 1 | 41.5 |
| load | tab1 | – | 1 | 41.5 |
| subtree_save | app | – | 1 | 41.5 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | entry_stat | load: checking | 120 | 4,985.4 | QUERY_INFO (macOS); none (Windows) |
| load | stat | load: before read | 120 | 4,985.4 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 120 | 4,985.4 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 120 | 4,985.4 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 120 | 4,985.4 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 41.5 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 41.5 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | scandir | load: listing | 1 | 41.5 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 41.5 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/18/run_a/d_txy_forc1.txt | 3 |
| stat | /share/2026/10/18/run_a/d_txy_forc2.txt | 3 |
| stat | /share/2026/10/18/run_a/d_txy_forc3.txt | 3 |
| stat | /share/2026/10/18/run_a/d_txy_forc4.txt | 3 |
| stat | /share/2026/10/18/run_a/d_txy_forc5.txt | 3 |
| stat | /share/2026/10/18/run_a/d_txy_forc6.txt | 3 |
| stat | /share/2026/10/18/run_a/d_txy_forc7.txt | 3 |
| stat | /share/2026/10/18/run_a/d_txy_forc8.txt | 3 |

## S1 select and load run_b (40 shots) (1 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | – | 1 | 44.9 |
| load | tab1 | – | 1 | 44.9 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | entry_stat | load: checking | 40 | 1,797.9 | QUERY_INFO (macOS); none (Windows) |
| load | stat | load: before read | 40 | 1,797.9 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 40 | 1,797.9 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 40 | 1,797.9 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 40 | 1,797.9 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 44.9 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 44.9 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | scandir | load: listing | 1 | 44.9 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 44.9 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/18/run_b/d_txy_forc1.txt | 3 |
| stat | /share/2026/10/18/run_b/d_txy_forc2.txt | 3 |
| stat | /share/2026/10/18/run_b/d_txy_forc3.txt | 3 |
| stat | /share/2026/10/18/run_b/d_txy_forc4.txt | 3 |
| stat | /share/2026/10/18/run_b/d_txy_forc5.txt | 3 |
| stat | /share/2026/10/18/run_b/d_txy_forc6.txt | 3 |
| stat | /share/2026/10/18/run_b/d_txy_forc7.txt | 3 |
| stat | /share/2026/10/18/run_b/d_txy_forc8.txt | 3 |

## S1 reselect run_b after 15 s (disk cached) (1 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| load | tab1 | – | 1 | 53.8 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | cached check: sample | 5 | 268.8 | CREATE/QUERY_INFO (or cached) |
| load | stat | cached check: folder | 1 | 53.8 | CREATE/QUERY_INFO (or cached) |

## S1 second tab: RAM-only folder, load run_r (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab2 | – | 2 | 58.0 |
| subtree_save | app | – | 2 | 58.0 |
| load | tab2 | – | 1 | 29.0 |
| details | tab2 | – | 1 | 29.0 |
| icons | tab2 | – | 1 | 29.0 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | entry_stat | load: checking | 120 | 3,478.5 | QUERY_INFO (macOS); none (Windows) |
| load | stat | load: before read | 120 | 3,478.5 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 120 | 3,478.5 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 120 | 3,478.5 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 120 | 3,478.5 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 2 | 58.0 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 2 | 58.0 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| icons | icon | folder icon | 2 | 58.0 | several (native lookup) |
| load | scandir | load: listing | 1 | 29.0 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 29.0 | CREATE/QUERY_INFO (or cached) |
| details | lstat | subfolder date | 1 | 29.0 | CREATE/QUERY_INFO (or cached) |
| details | scandir | listing | 1 | 29.0 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 1 | 29.0 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /ramshare/run_r/d_txy_forc1.txt | 3 |
| stat | /ramshare/run_r/d_txy_forc2.txt | 3 |
| stat | /ramshare/run_r/d_txy_forc3.txt | 3 |
| stat | /ramshare/run_r/d_txy_forc4.txt | 3 |
| stat | /ramshare/run_r/d_txy_forc5.txt | 3 |
| stat | /ramshare/run_r/d_txy_forc6.txt | 3 |
| stat | /ramshare/run_r/d_txy_forc7.txt | 3 |
| stat | /ramshare/run_r/d_txy_forc8.txt | 3 |

## S1 toolbar Refresh (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | scan_manual,listing_only | 5 | 130.4 |
| details | tab1 | – | 5 | 130.4 |
| icons | tab1 | – | 1 | 26.1 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| icons | icon | folder icon | 13 | 339.1 | several (native lookup) |
| details | lstat | subfolder date | 12 | 313.0 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 5 | 130.4 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 5 | 130.4 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | scandir | listing | 5 | 130.4 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 5 | 130.4 | CREATE/QUERY_INFO (or cached) |
| list | marker_open | root discovery | 1 | 26.1 | CREATE (a missing one: CREATE fails) |
| list | marker_fstat | root discovery | 1 | 26.1 | QUERY_INFO (or cached) |
| list | marker_read | root discovery | 1 | 26.1 | READ + CLOSE |

## S1 right-click Retry / Refresh on run_b (shown) (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | scan_manual | 1 | 29.9 |
| load | tab1 | full_check | 1 | 29.9 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | entry_stat | load: checking | 40 | 1,195.9 | QUERY_INFO (macOS); none (Windows) |
| load | stat | load: verifying | 40 | 1,195.9 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 29.9 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 29.9 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | scandir | load: listing | 1 | 29.9 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 29.9 | CREATE/QUERY_INFO (or cached) |

## S1 select and load run_live (1 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | – | 1 | 43.2 |
| load | tab1 | – | 1 | 43.2 |
| subtree_save | app | – | 1 | 43.2 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | entry_stat | load: checking | 30 | 1,296.5 | QUERY_INFO (macOS); none (Windows) |
| load | stat | load: before read | 30 | 1,296.5 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 30 | 1,296.5 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 30 | 1,296.5 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 30 | 1,296.5 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 43.2 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 43.2 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | scandir | load: listing | 1 | 43.2 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 43.2 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/19/run_live/d_txy_forc1.txt | 3 |
| stat | /share/2026/10/19/run_live/d_txy_forc2.txt | 3 |
| stat | /share/2026/10/19/run_live/d_txy_forc3.txt | 3 |
| stat | /share/2026/10/19/run_live/d_txy_forc4.txt | 3 |
| stat | /share/2026/10/19/run_live/d_txy_forc5.txt | 3 |
| stat | /share/2026/10/19/run_live/d_txy_forc6.txt | 3 |
| stat | /share/2026/10/19/run_live/d_txy_forc7.txt | 3 |
| stat | /share/2026/10/19/run_live/d_txy_forc8.txt | 3 |

## S1 Live on, writer adds 12 shots every 4 s (1004 written over 7.5 s, 1009 pauses 4 s mid-file) (60 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| live | tab1:live | – | 19 | 19.0 |
| subtree_save | app | – | 10 | 10.0 |
| load | tab1:live-save | save | 1 | 1.0 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| live | stat | live: sample | 80 | 80.1 | CREATE/QUERY_INFO (or cached) |
| load | entry_stat | save: checking | 42 | 42.1 | QUERY_INFO (macOS); none (Windows) |
| live | stat | live: new file | 30 | 30.1 | CREATE/QUERY_INFO (or cached) |
| live | marker_open | live: identity | 20 | 20.0 | CREATE (a missing one: CREATE fails) |
| live | stat | live: folder | 19 | 19.0 | CREATE/QUERY_INFO (or cached) |
| live | scandir | live: listing | 16 | 16.0 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| live | marker_fstat | live: identity | 16 | 16.0 | QUERY_INFO (or cached) |
| live | marker_read | live: identity | 16 | 16.0 | READ + CLOSE |
| live | stat | live: before read | 10 | 10.0 | CREATE/QUERY_INFO (or cached) |
| live | read | live: read | 10 | 10.0 | CREATE + READ×n + CLOSE |
| live | stat | live: after read | 10 | 10.0 | CREATE/QUERY_INFO (or cached) |
| live | stat | folder mtime | 10 | 10.0 | CREATE/QUERY_INFO (or cached) |
| live | stat | live: pending file | 3 | 3.0 | CREATE/QUERY_INFO (or cached) |
| load | scandir | save: listing | 1 | 1.0 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | marker_open | save: identity | 1 | 1.0 | CREATE (a missing one: CREATE fails) |
| load | marker_fstat | save: identity | 1 | 1.0 | QUERY_INFO (or cached) |
| load | marker_read | save: identity | 1 | 1.0 | READ + CLOSE |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/19/run_live | 29 |
| scandir | /share/2026/10/19/run_live | 17 |
| marker_open | /share/.helab-root | 17 |
| marker_fstat | /share/.helab-root | 17 |
| marker_read | /share/.helab-root | 17 |
| stat | /share/2026/10/19/run_live/d_txy_forc1.txt | 16 |
| stat | /share/2026/10/19/run_live/d_txy_forc1004.txt | 9 |
| stat | /share/2026/10/19/run_live/d_txy_forc1003.txt | 8 |

## S1 Live on, writer done: 15 s to settle (15 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| live | tab1:live | live_since | 3 | 12.0 |
| live | tab1:live | – | 2 | 8.0 |
| subtree_save | app | – | 1 | 4.0 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| live | stat | live: sample | 10 | 40.0 | CREATE/QUERY_INFO (or cached) |
| live | stat | live: folder | 5 | 20.0 | CREATE/QUERY_INFO (or cached) |
| live | stat | live: new file | 3 | 12.0 | CREATE/QUERY_INFO (or cached) |
| live | scandir | live: listing | 2 | 8.0 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| live | marker_open | live: identity | 2 | 8.0 | CREATE (a missing one: CREATE fails) |
| live | marker_fstat | live: identity | 2 | 8.0 | QUERY_INFO (or cached) |
| live | marker_read | live: identity | 2 | 8.0 | READ + CLOSE |
| live | stat | live: before read | 2 | 8.0 | CREATE/QUERY_INFO (or cached) |
| live | read | live: read | 2 | 8.0 | CREATE + READ×n + CLOSE |
| live | stat | live: after read | 2 | 8.0 | CREATE/QUERY_INFO (or cached) |
| live | stat | folder mtime | 2 | 8.0 | CREATE/QUERY_INFO (or cached) |
| live | stat | live: pending file | 1 | 4.0 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/19/run_live | 7 |
| stat | /share/2026/10/19/run_live/d_txy_forc1012.txt | 5 |
| stat | /share/2026/10/19/run_live/d_txy_forc1011.txt | 4 |

## S1 Live on, nothing new, 60 s (60 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| live | tab1:live | live_since | 19 | 19.0 |
| live | tab1:live | – | 1 | 1.0 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| live | stat | live: folder | 20 | 20.0 | CREATE/QUERY_INFO (or cached) |
| live | stat | live: sample | 5 | 5.0 | CREATE/QUERY_INFO (or cached) |
| live | scandir | live: listing | 1 | 1.0 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| live | marker_open | live: identity | 1 | 1.0 | CREATE (a missing one: CREATE fails) |
| live | marker_fstat | live: identity | 1 | 1.0 | QUERY_INFO (or cached) |
| live | marker_read | live: identity | 1 | 1.0 | READ + CLOSE |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/19/run_live | 20 |

Per minute: 0: 29, 1: 0

## S1 Live off (saves new shots) (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| load | tab1:live-save | save | 1 | 29.9 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | entry_stat | save: checking | 42 | 1,253.8 | QUERY_INFO (macOS); none (Windows) |
| load | scandir | save: listing | 1 | 29.9 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | marker_open | save: identity | 1 | 29.9 | CREATE (a missing one: CREATE fails) |
| load | marker_fstat | save: identity | 1 | 29.9 | QUERY_INFO (or cached) |
| load | marker_read | save: identity | 1 | 29.9 | READ + CLOSE |

## S1 load run_stall while its new shot 2001 stalls 8 s mid-file (selected 6.5 s in) (9 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | – | 1 | 6.5 |
| load | tab1 | – | 1 | 6.5 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | entry_stat | load: checking | 11 | 71.0 | QUERY_INFO (macOS); none (Windows) |
| load | stat | load: before read | 11 | 71.0 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 11 | 71.0 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 11 | 71.0 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 11 | 71.0 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 6.5 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 6.5 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | scandir | load: listing | 1 | 6.5 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 6.5 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/19/run_stall/d_txy_forc1.txt | 3 |
| stat | /share/2026/10/19/run_stall/d_txy_forc2.txt | 3 |
| stat | /share/2026/10/19/run_stall/d_txy_forc3.txt | 3 |
| stat | /share/2026/10/19/run_stall/d_txy_forc4.txt | 3 |
| stat | /share/2026/10/19/run_stall/d_txy_forc5.txt | 3 |
| stat | /share/2026/10/19/run_stall/d_txy_forc6.txt | 3 |
| stat | /share/2026/10/19/run_stall/d_txy_forc7.txt | 3 |
| stat | /share/2026/10/19/run_stall/d_txy_forc8.txt | 3 |

## S1 simulated mount change (a listing reports another mount table), 30 s (30 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| volumes_verify | app | – | 1 | 2.0 |
| roots_verify | app | – | 1 | 2.0 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| roots_verify | stat | roots_verify: root folder | 1 | 2.0 | CREATE/QUERY_INFO (or cached) |
| roots_verify | lstat | roots_verify: marker | 1 | 2.0 | CREATE/QUERY_INFO (or cached) |
| roots_verify | marker_open | root discovery | 1 | 2.0 | CREATE (a missing one: CREATE fails) |
| roots_verify | marker_fstat | root discovery | 1 | 2.0 | QUERY_INFO (or cached) |
| roots_verify | marker_read | root discovery | 1 | 2.0 | READ + CLOSE |

## S1 a listing reports the real mount table again, 15 s (16 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | scan_manual | 1 | 3.7 |
| details | tab1 | scan_manual | 1 | 3.7 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| details | lstat | subfolder date | 5 | 18.7 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 3.7 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 3.7 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | scandir | listing | 1 | 3.7 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 1 | 3.7 | CREATE/QUERY_INFO (or cached) |

## S1 select a folder that can't be listed (permission), 20 s (20 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | – | 1 | 3.0 |
| scan_history | app | – | 1 | 3.0 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| list | lstat | listing: marker | 1 | 3.0 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 3.0 | CREATE + QUERY_DIRECTORY×n + CLOSE |

## S1 select a folder whose file read hangs (timeouts 3/4/5 s), until it fails (14 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| load | tab1 | – | 3 | 12.6 |
| list | tab1 | – | 1 | 4.2 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | entry_stat | load: checking | 60 | 252.9 | QUERY_INFO (macOS); none (Windows) |
| load | stat | load: before read | 22 | 92.7 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 19 | 80.1 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 19 | 80.1 | CREATE/QUERY_INFO (or cached) |
| load | scandir | load: listing | 3 | 12.6 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 3 | 12.6 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 4.2 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 4.2 | CREATE + QUERY_DIRECTORY×n + CLOSE |

Most repeated:

| Op | Path | Times |
|---|---|---|
| scandir | /share/2026/10/19/stuck | 4 |
| entry_stat | /share/2026/10/19/stuck/d_txy_forc14.txt | 3 |
| entry_stat | /share/2026/10/19/stuck/d_txy_forc15.txt | 3 |
| entry_stat | /share/2026/10/19/stuck/d_txy_forc17.txt | 3 |
| entry_stat | /share/2026/10/19/stuck/d_txy_forc16.txt | 3 |
| entry_stat | /share/2026/10/19/stuck/d_txy_forc12.txt | 3 |
| entry_stat | /share/2026/10/19/stuck/d_txy_forc13.txt | 3 |
| entry_stat | /share/2026/10/19/stuck/d_txy_forc11.txt | 3 |

## Files touched while the fake writer was writing them

| Op | Reason | Request | File | t |
|---|---|---|---|---|
| stat | live: new file | live | d_txy_forc1004.txt | 1792412089.59 |
| stat | live: new file | live | d_txy_forc1004.txt | 1792412092.60 |
| stat | live: pending file | live | d_txy_forc1004.txt | 1792412096.01 |
| stat | live: new file | live | d_txy_forc1009.txt | 1792412117.64 |
| stat | live: new file | live | d_txy_forc1009.txt | 1792412120.59 |
| entry_stat | load: checking | load | d_txy_forc2001.txt | 1792412220.83 |
| stat | load: before read | load | d_txy_forc2001.txt | 1792412220.84 |
| read | load: read | load | d_txy_forc2001.txt | 1792412220.84 |
| stat | load: after read | load | d_txy_forc2001.txt | 1792412220.84 |
| stat | load: verifying | load | d_txy_forc2001.txt | 1792412220.84 |

## Operations on files modified under 5 s before (by the mtime they saw)

| Op | Reason | Request | Count | Youngest age (s) |
|---|---|---|---|---|
| stat | live: new file | live | 20 | 0.02 |
| stat | live: pending file | live | 3 | 1.78 |
| entry_stat | save: checking | load | 1 | 2.96 |

## GUI-process source calls (scenarios.py's hook)

None.
