# I/O trace summary: <out>.s2.trace.jsonl

## Phases

| Phase | Seconds | Helpers | Source ops | Ops/min | Listings | Stats | Reads | Tail/marker/icon | GUI-process |
|---|---|---|---|---|---|---|---|---|---|
| S2 startup | 2 | 9 | 14 | 447.2 | 2 | 7 | 0 (0.0 MB) | 5 | 0 |
| S2 idle 60 s, tree open | 60 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S2 expand to run_a (saved badges) | 2 | 7 | 22 | 595.4 | 6 | 11 | 0 (0.0 MB) | 5 | 0 |
| S2 select run_a: cached data, checked beside it | 1 | 2 | 6 | 293.5 | 0 | 6 | 0 (0.0 MB) | 0 | 0 |
| S2 run_b gained a shot since: select it | 2 | 4 | 174 | 4,834.8 | 3 | 170 | 1 (0.0 MB) | 0 | 0 |
| S2 RAM-only tab: load run_r (no .helab-root) | 2 | 7 | 611 | 14,893.5 | 4 | 485 | 120 (3.0 MB) | 2 | 0 |
| S2 idle 15 s | 15 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S2 reselect run_r after 15 s (RAM only, unchanged) | 5 | 4 | 249 | 3,178.4 | 4 | 245 | 0 (0.0 MB) | 0 | 0 |
| S2 idle 15 s, then reselect run_a in tab 1 (disk cached, unchanged) | 19 | 1 | 6 | 18.8 | 0 | 6 | 0 (0.0 MB) | 0 | 0 |
| S2 idle 60 s at the end | 60 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S2 quit | 2 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S2 end | 0 | 0 | 0 | – | 0 | 0 | 0 (0.0 MB) | 0 | 0 |

## S2 startup (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| cache_admin | app | – | 2 | 63.9 |
| volumes_verify | app | – | 2 | 63.9 |
| roots_verify | app | – | 1 | 31.9 |
| resolve | tab1 | – | 1 | 31.9 |
| list | tab1 | – | 1 | 31.9 |
| details | tab1 | – | 1 | 31.9 |
| icons | tab1 | – | 1 | 31.9 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| icons | icon | folder icon | 3 | 95.8 | several (native lookup) |
| details | lstat | subfolder date | 2 | 63.9 | CREATE/QUERY_INFO (or cached) |
| resolve | stat | resolve | 1 | 31.9 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 31.9 | CREATE/QUERY_INFO (or cached) |
| list | marker_read | root discovery | 1 | 31.9 | CREATE (+ READ + CLOSE) |
| list | scandir | listing | 1 | 31.9 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| roots_verify | stat | roots_verify: root folder | 1 | 31.9 | CREATE/QUERY_INFO (or cached) |
| roots_verify | lstat | roots_verify: marker | 1 | 31.9 | CREATE/QUERY_INFO (or cached) |
| roots_verify | marker_read | root discovery | 1 | 31.9 | CREATE (+ READ + CLOSE) |
| details | scandir | listing | 1 | 31.9 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 1 | 31.9 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share | 3 |

## S2 expand to run_a (saved badges) (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | – | 3 | 81.2 |
| details | tab1 | – | 3 | 81.2 |
| icons | tab1 | – | 1 | 27.1 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| details | lstat | subfolder date | 5 | 135.3 | CREATE/QUERY_INFO (or cached) |
| icons | icon | folder icon | 5 | 135.3 | several (native lookup) |
| list | lstat | listing: marker | 3 | 81.2 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 3 | 81.2 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | scandir | listing | 3 | 81.2 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 3 | 81.2 | CREATE/QUERY_INFO (or cached) |

## S2 select run_a: cached data, checked beside it (1 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| cached | tab1 | – | 1 | 48.9 |
| load | tab1 | cache_base | 1 | 48.9 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | cached check: sample | 5 | 244.6 | CREATE/QUERY_INFO (or cached) |
| load | stat | cached check: folder | 1 | 48.9 | CREATE/QUERY_INFO (or cached) |

## S2 run_b gained a shot since: select it (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| cached | tab1 | – | 1 | 27.8 |
| load | tab1 | cache_base | 1 | 27.8 |
| list | tab1 | – | 1 | 27.8 |
| details | tab1 | – | 1 | 27.8 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | load: checking | 41 | 1,139.2 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 41 | 1,139.2 | CREATE/QUERY_INFO (or cached) |
| load | stat | cache save: verifying | 41 | 1,139.2 | CREATE/QUERY_INFO (or cached) |
| details | entry_stat | fingerprint | 41 | 1,139.2 | QUERY_INFO (macOS); none (Windows) |
| load | stat | cached check: folder | 1 | 27.8 | CREATE/QUERY_INFO (or cached) |
| load | scandir | load: listing | 1 | 27.8 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 27.8 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: before read | 1 | 27.8 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 1 | 27.8 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 1 | 27.8 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 27.8 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 27.8 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | scandir | listing | 1 | 27.8 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 1 | 27.8 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/18/run_b/d_txy_forc41.txt | 5 |
| stat | /share/2026/10/18/run_b | 3 |
| scandir | /share/2026/10/18/run_b | 3 |
| stat | /share/2026/10/18/run_b/d_txy_forc1.txt | 3 |
| stat | /share/2026/10/18/run_b/d_txy_forc2.txt | 3 |
| stat | /share/2026/10/18/run_b/d_txy_forc3.txt | 3 |
| stat | /share/2026/10/18/run_b/d_txy_forc4.txt | 3 |
| stat | /share/2026/10/18/run_b/d_txy_forc5.txt | 3 |

## S2 RAM-only tab: load run_r (no .helab-root) (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab2 | – | 2 | 48.8 |
| subtree_save | app | – | 2 | 48.8 |
| load | tab2 | – | 1 | 24.4 |
| details | tab2 | – | 1 | 24.4 |
| icons | tab2 | – | 1 | 24.4 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | load: checking | 120 | 2,925.1 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: before read | 120 | 2,925.1 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 120 | 2,925.1 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 120 | 2,925.1 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 120 | 2,925.1 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 2 | 48.8 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 2 | 48.8 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| icons | icon | folder icon | 2 | 48.8 | several (native lookup) |
| load | scandir | load: listing | 1 | 24.4 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 24.4 | CREATE/QUERY_INFO (or cached) |
| details | lstat | subfolder date | 1 | 24.4 | CREATE/QUERY_INFO (or cached) |
| details | scandir | listing | 1 | 24.4 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 1 | 24.4 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /ramshare/run_r/d_txy_forc1.txt | 4 |
| stat | /ramshare/run_r/d_txy_forc2.txt | 4 |
| stat | /ramshare/run_r/d_txy_forc3.txt | 4 |
| stat | /ramshare/run_r/d_txy_forc4.txt | 4 |
| stat | /ramshare/run_r/d_txy_forc5.txt | 4 |
| stat | /ramshare/run_r/d_txy_forc6.txt | 4 |
| stat | /ramshare/run_r/d_txy_forc7.txt | 4 |
| stat | /ramshare/run_r/d_txy_forc8.txt | 4 |

## S2 reselect run_r after 15 s (RAM only, unchanged) (5 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab2 | automatic | 2 | 25.5 |
| details | tab2 | – | 1 | 12.8 |
| load | tab2 | – | 1 | 12.8 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | load: checking | 120 | 1,531.7 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 120 | 1,531.7 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 2 | 25.5 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 2 | 25.5 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | lstat | subfolder date | 1 | 12.8 | CREATE/QUERY_INFO (or cached) |
| details | scandir | listing | 1 | 12.8 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 1 | 12.8 | CREATE/QUERY_INFO (or cached) |
| load | scandir | load: listing | 1 | 12.8 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 12.8 | CREATE/QUERY_INFO (or cached) |

## S2 idle 15 s, then reselect run_a in tab 1 (disk cached, unchanged) (19 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| load | tab1 | – | 1 | 3.1 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | cached check: sample | 5 | 15.7 | CREATE/QUERY_INFO (or cached) |
| load | stat | cached check: folder | 1 | 3.1 | CREATE/QUERY_INFO (or cached) |

## Operations on files modified under 5 s before (by the mtime they saw)

None.

## GUI-process source calls (scenarios.py's hook)

None.
