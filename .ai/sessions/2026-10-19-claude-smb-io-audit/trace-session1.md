# I/O trace summary: <out>.s1.trace.jsonl

## Phases

| Phase | Seconds | Helpers | Source ops | Ops/min | Listings | Stats | Reads | Tail/marker/icon | GUI-process |
|---|---|---|---|---|---|---|---|---|---|
| S1 startup | 2 | 8 | 11 | 367.2 | 2 | 5 | 0 (0.0 MB) | 4 | 0 |
| S1 idle 60 s, tree open | 60 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 expand 2026/10/18 and 19 | 2 | 9 | 36 | 1,006.0 | 8 | 18 | 0 (0.0 MB) | 10 | 0 |
| S1 select and load run_a (120 shots) | 2 | 3 | 724 | 28,161.1 | 2 | 602 | 120 (3.0 MB) | 0 | 0 |
| S1 select and load run_b (40 shots) | 1 | 2 | 244 | 10,530.2 | 2 | 202 | 40 (1.0 MB) | 0 | 0 |
| S1 reselect run_a within 10 s | 4 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 idle 15 s | 15 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 reselect run_b after 15 s (disk cached) | 1 | 1 | 6 | 322.8 | 0 | 6 | 0 (0.0 MB) | 0 | 0 |
| S1 second tab: RAM-only folder, load run_r | 2 | 7 | 611 | 15,981.2 | 4 | 485 | 120 (3.0 MB) | 2 | 0 |
| S1 tab switch 1 (to tab 1) after 15 s | 16 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 tab switch 2 (to tab 2) after 15 s | 16 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 tab switch 3 (to tab 1) after 15 s | 16 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 tab switch 4 (to tab 2) after 15 s | 17 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 toolbar Refresh | 2 | 11 | 46 | 1,239.4 | 10 | 22 | 0 (0.0 MB) | 14 | 0 |
| S1 right-click Retry / Refresh on run_b (shown) | 2 | 2 | 84 | 2,499.4 | 2 | 82 | 0 (0.0 MB) | 0 | 0 |
| S1 select and load run_live | 1 | 3 | 184 | 8,051.6 | 2 | 152 | 30 (0.8 MB) | 0 | 0 |
| S1 Live on, writer adds 12 shots every 4 s (1004 written over 7.5 s, 1009 stalls 8 s mid-file) | 64 | 30 | 460 | 433.9 | 20 | 313 | 21 (0.5 MB) | 106 | 0 |
| S1 Live on, writer done: 15 s to settle | 15 | 5 | 35 | 140.0 | 2 | 21 | 1 (0.0 MB) | 11 | 0 |
| S1 Live on, nothing new, 60 s | 60 | 20 | 31 | 31.0 | 1 | 25 | 0 (0.0 MB) | 5 | 0 |
| S1 Live off (saves new shots) | 2 | 1 | 129 | 3,858.5 | 1 | 127 | 1 (0.0 MB) | 0 | 0 |
| S1 load run_stall while its new shot 2001 stalls 8 s mid-file (selected 6.5 s in) | 9 | 4 | 73 | 468.0 | 2 | 59 | 11 (0.3 MB) | 1 | 0 |
| S1 simulated mount change (a listing reports another mount table), 30 s | 30 | 803 | 1242 | 2,483.3 | 0 | 828 | 0 (0.0 MB) | 414 | 0 |
| S1 a listing reports the real mount table again, 15 s | 16 | 4 | 12 | 45.0 | 2 | 9 | 0 (0.0 MB) | 1 | 0 |
| S1 select a folder that can't be listed (permission), 20 s | 20 | 2 | 2 | 6.0 | 1 | 1 | 0 (0.0 MB) | 0 | 0 |
| S1 select a folder whose file read hangs (timeouts 3/4/5 s), until it fails | 14 | 4 | 128 | 540.0 | 4 | 105 | 19 (0.5 MB) | 0 | 0 |
| S1 idle 60 s at the end | 60 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 quit | 2 | 0 | 0 | 0.0 | 0 | 0 | 0 (0.0 MB) | 0 | 0 |
| S1 end | 0 | 0 | 0 | – | 0 | 0 | 0 (0.0 MB) | 0 | 0 |

## S1 startup (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| cache_admin | app | – | 2 | 66.8 |
| roots_verify | app | – | 1 | 33.4 |
| resolve | tab1 | – | 1 | 33.4 |
| volumes_verify | app | – | 1 | 33.4 |
| list | tab1 | – | 1 | 33.4 |
| details | tab1 | – | 1 | 33.4 |
| icons | tab1 | – | 1 | 33.4 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| icons | icon | folder icon | 3 | 100.2 | several (native lookup) |
| details | lstat | subfolder date | 2 | 66.8 | CREATE/QUERY_INFO (or cached) |
| resolve | stat | resolve | 1 | 33.4 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 33.4 | CREATE/QUERY_INFO (or cached) |
| list | marker_read | root discovery | 1 | 33.4 | CREATE (+ READ + CLOSE) |
| list | scandir | listing | 1 | 33.4 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | scandir | listing | 1 | 33.4 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 1 | 33.4 | CREATE/QUERY_INFO (or cached) |

## S1 expand 2026/10/18 and 19 (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | – | 4 | 111.8 |
| details | tab1 | – | 4 | 111.8 |
| icons | tab1 | – | 1 | 27.9 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| details | lstat | subfolder date | 10 | 279.4 | CREATE/QUERY_INFO (or cached) |
| icons | icon | folder icon | 10 | 279.4 | several (native lookup) |
| list | lstat | listing: marker | 4 | 111.8 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 4 | 111.8 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | scandir | listing | 4 | 111.8 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 4 | 111.8 | CREATE/QUERY_INFO (or cached) |

## S1 select and load run_a (120 shots) (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | – | 1 | 38.9 |
| load | tab1 | – | 1 | 38.9 |
| subtree_save | app | – | 1 | 38.9 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | load: checking | 120 | 4,667.6 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: before read | 120 | 4,667.6 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 120 | 4,667.6 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 120 | 4,667.6 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 120 | 4,667.6 | CREATE/QUERY_INFO (or cached) |
| load | stat | cache save: verifying | 120 | 4,667.6 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 38.9 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 38.9 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | scandir | load: listing | 1 | 38.9 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 38.9 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/18/run_a/d_txy_forc1.txt | 5 |
| stat | /share/2026/10/18/run_a/d_txy_forc2.txt | 5 |
| stat | /share/2026/10/18/run_a/d_txy_forc3.txt | 5 |
| stat | /share/2026/10/18/run_a/d_txy_forc4.txt | 5 |
| stat | /share/2026/10/18/run_a/d_txy_forc5.txt | 5 |
| stat | /share/2026/10/18/run_a/d_txy_forc6.txt | 5 |
| stat | /share/2026/10/18/run_a/d_txy_forc7.txt | 5 |
| stat | /share/2026/10/18/run_a/d_txy_forc8.txt | 5 |

## S1 select and load run_b (40 shots) (1 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | – | 1 | 43.2 |
| load | tab1 | – | 1 | 43.2 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | load: checking | 40 | 1,726.3 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: before read | 40 | 1,726.3 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 40 | 1,726.3 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 40 | 1,726.3 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 40 | 1,726.3 | CREATE/QUERY_INFO (or cached) |
| load | stat | cache save: verifying | 40 | 1,726.3 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 43.2 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 43.2 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | scandir | load: listing | 1 | 43.2 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 43.2 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/18/run_b/d_txy_forc1.txt | 5 |
| stat | /share/2026/10/18/run_b/d_txy_forc2.txt | 5 |
| stat | /share/2026/10/18/run_b/d_txy_forc3.txt | 5 |
| stat | /share/2026/10/18/run_b/d_txy_forc4.txt | 5 |
| stat | /share/2026/10/18/run_b/d_txy_forc5.txt | 5 |
| stat | /share/2026/10/18/run_b/d_txy_forc6.txt | 5 |
| stat | /share/2026/10/18/run_b/d_txy_forc7.txt | 5 |
| stat | /share/2026/10/18/run_b/d_txy_forc8.txt | 5 |

## S1 reselect run_b after 15 s (disk cached) (1 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| load | tab1 | – | 1 | 53.8 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | cached check: sample | 5 | 269.0 | CREATE/QUERY_INFO (or cached) |
| load | stat | cached check: folder | 1 | 53.8 | CREATE/QUERY_INFO (or cached) |

## S1 second tab: RAM-only folder, load run_r (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab2 | – | 2 | 52.3 |
| subtree_save | app | – | 2 | 52.3 |
| load | tab2 | – | 1 | 26.2 |
| details | tab2 | – | 1 | 26.2 |
| icons | tab2 | – | 1 | 26.2 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | load: checking | 120 | 3,138.7 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: before read | 120 | 3,138.7 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 120 | 3,138.7 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 120 | 3,138.7 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 120 | 3,138.7 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 2 | 52.3 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 2 | 52.3 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| icons | icon | folder icon | 2 | 52.3 | several (native lookup) |
| load | scandir | load: listing | 1 | 26.2 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 26.2 | CREATE/QUERY_INFO (or cached) |
| details | lstat | subfolder date | 1 | 26.2 | CREATE/QUERY_INFO (or cached) |
| details | scandir | listing | 1 | 26.2 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 1 | 26.2 | CREATE/QUERY_INFO (or cached) |

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

## S1 toolbar Refresh (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | scan_manual,listing_only | 5 | 134.7 |
| details | tab1 | – | 5 | 134.7 |
| icons | tab1 | – | 1 | 26.9 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| icons | icon | folder icon | 13 | 350.3 | several (native lookup) |
| details | lstat | subfolder date | 12 | 323.3 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 5 | 134.7 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 5 | 134.7 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | scandir | listing | 5 | 134.7 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| details | stat | folder mtime | 5 | 134.7 | CREATE/QUERY_INFO (or cached) |
| list | marker_read | root discovery | 1 | 26.9 | CREATE (+ READ + CLOSE) |

## S1 right-click Retry / Refresh on run_b (shown) (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | scan_manual | 1 | 29.8 |
| load | tab1 | full_check | 1 | 29.8 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | load: checking | 40 | 1,190.2 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 40 | 1,190.2 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 29.8 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 29.8 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | scandir | load: listing | 1 | 29.8 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 29.8 | CREATE/QUERY_INFO (or cached) |

## S1 select and load run_live (1 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | – | 1 | 43.8 |
| load | tab1 | – | 1 | 43.8 |
| subtree_save | app | – | 1 | 43.8 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | load: checking | 30 | 1,312.8 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: before read | 30 | 1,312.8 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 30 | 1,312.8 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 30 | 1,312.8 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 30 | 1,312.8 | CREATE/QUERY_INFO (or cached) |
| load | stat | cache save: verifying | 30 | 1,312.8 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 43.8 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 43.8 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | scandir | load: listing | 1 | 43.8 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 43.8 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/19/run_live/d_txy_forc1.txt | 5 |
| stat | /share/2026/10/19/run_live/d_txy_forc2.txt | 5 |
| stat | /share/2026/10/19/run_live/d_txy_forc3.txt | 5 |
| stat | /share/2026/10/19/run_live/d_txy_forc4.txt | 5 |
| stat | /share/2026/10/19/run_live/d_txy_forc5.txt | 5 |
| stat | /share/2026/10/19/run_live/d_txy_forc6.txt | 5 |
| stat | /share/2026/10/19/run_live/d_txy_forc7.txt | 5 |
| stat | /share/2026/10/19/run_live/d_txy_forc8.txt | 5 |

## S1 Live on, writer adds 12 shots every 4 s (1004 written over 7.5 s, 1009 stalls 8 s mid-file) (64 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| live | tab1:live | – | 19 | 17.9 |
| subtree_save | app | – | 10 | 9.4 |
| load | tab1:live-save | save | 1 | 0.9 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| live | marker_read | live: identity | 95 | 89.6 | CREATE (+ READ + CLOSE) |
| live | stat | live: sample | 95 | 89.6 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: checking | 42 | 39.6 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 41 | 38.7 | CREATE/QUERY_INFO (or cached) |
| load | stat | cache save: verifying | 41 | 38.7 | CREATE/QUERY_INFO (or cached) |
| live | stat | live: new file | 31 | 29.2 | CREATE/QUERY_INFO (or cached) |
| live | stat | live: folder | 19 | 17.9 | CREATE/QUERY_INFO (or cached) |
| live | scandir | live: listing | 19 | 17.9 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| live | stat | live: last row | 11 | 10.4 | CREATE/QUERY_INFO (or cached) |
| live | read_tail | live: last row | 11 | 10.4 | CREATE + READ + CLOSE |
| live | stat | live: before read | 10 | 9.4 | CREATE/QUERY_INFO (or cached) |
| live | read | live: read | 10 | 9.4 | CREATE + READ×n + CLOSE |
| live | stat | live: after read | 10 | 9.4 | CREATE/QUERY_INFO (or cached) |
| live | stat | folder mtime | 10 | 9.4 | CREATE/QUERY_INFO (or cached) |
| load | read | cache save: read | 10 | 9.4 | CREATE + READ×n + CLOSE |
| load | scandir | load: listing | 1 | 0.9 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 0.9 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: before read | 1 | 0.9 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 1 | 0.9 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 1 | 0.9 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/19/run_live | 30 |
| stat | /share/2026/10/19/run_live/d_txy_forc1.txt | 22 |
| scandir | /share/2026/10/19/run_live | 20 |
| marker_read | /share/2026/10/19/run_live/.helab-root | 19 |
| marker_read | /share/2026/10/19/.helab-root | 19 |
| marker_read | /share/2026/10/.helab-root | 19 |
| marker_read | /share/2026/.helab-root | 19 |
| marker_read | /share/.helab-root | 19 |

Per minute: 0: 321, 1: 139

## S1 Live on, writer done: 15 s to settle (15 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| live | tab1:live | live_since | 3 | 12.0 |
| live | tab1:live | – | 2 | 8.0 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| live | marker_read | live: identity | 10 | 40.0 | CREATE (+ READ + CLOSE) |
| live | stat | live: sample | 10 | 40.0 | CREATE/QUERY_INFO (or cached) |
| live | stat | live: folder | 5 | 20.0 | CREATE/QUERY_INFO (or cached) |
| live | scandir | live: listing | 2 | 8.0 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| live | stat | live: new file | 2 | 8.0 | CREATE/QUERY_INFO (or cached) |
| live | stat | live: last row | 1 | 4.0 | CREATE/QUERY_INFO (or cached) |
| live | read_tail | live: last row | 1 | 4.0 | CREATE + READ + CLOSE |
| live | stat | live: before read | 1 | 4.0 | CREATE/QUERY_INFO (or cached) |
| live | read | live: read | 1 | 4.0 | CREATE + READ×n + CLOSE |
| live | stat | live: after read | 1 | 4.0 | CREATE/QUERY_INFO (or cached) |
| live | stat | folder mtime | 1 | 4.0 | CREATE/QUERY_INFO (or cached) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/19/run_live | 6 |
| stat | /share/2026/10/19/run_live/d_txy_forc1012.txt | 5 |

## S1 Live on, nothing new, 60 s (60 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| live | tab1:live | live_since | 19 | 19.0 |
| live | tab1:live | – | 1 | 1.0 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| live | stat | live: folder | 20 | 20.0 | CREATE/QUERY_INFO (or cached) |
| live | marker_read | live: identity | 5 | 5.0 | CREATE (+ READ + CLOSE) |
| live | stat | live: sample | 5 | 5.0 | CREATE/QUERY_INFO (or cached) |
| live | scandir | live: listing | 1 | 1.0 | CREATE + QUERY_DIRECTORY×n + CLOSE |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/19/run_live | 20 |

Per minute: 0: 31, 1: 0

## S1 Live off (saves new shots) (2 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| load | tab1:live-save | save | 1 | 29.9 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | load: checking | 42 | 1,256.2 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 42 | 1,256.2 | CREATE/QUERY_INFO (or cached) |
| load | stat | cache save: verifying | 42 | 1,256.2 | CREATE/QUERY_INFO (or cached) |
| load | scandir | load: listing | 1 | 29.9 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 29.9 | CREATE/QUERY_INFO (or cached) |
| load | read | cache save: read | 1 | 29.9 | CREATE + READ×n + CLOSE |

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

## S1 load run_stall while its new shot 2001 stalls 8 s mid-file (selected 6.5 s in) (9 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| list | tab1 | – | 1 | 6.4 |
| volumes_verify | app | – | 1 | 6.4 |
| load | tab1 | – | 1 | 6.4 |
| roots_verify | app | – | 1 | 6.4 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | load: checking | 11 | 70.5 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: before read | 11 | 70.5 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 11 | 70.5 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 11 | 70.5 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: verifying | 11 | 70.5 | CREATE/QUERY_INFO (or cached) |
| load | stat | cache save: verifying | 11 | 70.5 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 6.4 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 6.4 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | scandir | load: listing | 1 | 6.4 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 1 | 6.4 | CREATE/QUERY_INFO (or cached) |
| roots_verify | stat | roots_verify: root folder | 1 | 6.4 | CREATE/QUERY_INFO (or cached) |
| roots_verify | lstat | roots_verify: marker | 1 | 6.4 | CREATE/QUERY_INFO (or cached) |
| roots_verify | marker_read | root discovery | 1 | 6.4 | CREATE (+ READ + CLOSE) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/19/run_stall/d_txy_forc1.txt | 5 |
| stat | /share/2026/10/19/run_stall/d_txy_forc2.txt | 5 |
| stat | /share/2026/10/19/run_stall/d_txy_forc3.txt | 5 |
| stat | /share/2026/10/19/run_stall/d_txy_forc4.txt | 5 |
| stat | /share/2026/10/19/run_stall/d_txy_forc5.txt | 5 |
| stat | /share/2026/10/19/run_stall/d_txy_forc6.txt | 5 |
| stat | /share/2026/10/19/run_stall/d_txy_forc7.txt | 5 |
| stat | /share/2026/10/19/run_stall/d_txy_forc8.txt | 5 |

## S1 simulated mount change (a listing reports another mount table), 30 s (30 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| roots_verify | app | – | 414 | 827.8 |
| volumes_verify | app | – | 389 | 777.8 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| roots_verify | stat | roots_verify: root folder | 414 | 827.8 | CREATE/QUERY_INFO (or cached) |
| roots_verify | lstat | roots_verify: marker | 414 | 827.8 | CREATE/QUERY_INFO (or cached) |
| roots_verify | marker_read | root discovery | 414 | 827.8 | CREATE (+ READ + CLOSE) |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share | 414 |
| lstat | /share/.helab-root | 414 |
| marker_read | /share/.helab-root | 414 |

## S1 a listing reports the real mount table again, 15 s (16 s)

| Request | For | Flags | Helpers | Per min |
|---|---|---|---|---|
| volumes_verify | app | – | 1 | 3.7 |
| roots_verify | app | – | 1 | 3.7 |
| list | tab1 | scan_manual | 1 | 3.7 |
| details | tab1 | scan_manual | 1 | 3.7 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| details | lstat | subfolder date | 5 | 18.7 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 3.7 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 3.7 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| roots_verify | stat | roots_verify: root folder | 1 | 3.7 | CREATE/QUERY_INFO (or cached) |
| roots_verify | lstat | roots_verify: marker | 1 | 3.7 | CREATE/QUERY_INFO (or cached) |
| roots_verify | marker_read | root discovery | 1 | 3.7 | CREATE (+ READ + CLOSE) |
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
| load | tab1 | – | 3 | 12.7 |
| list | tab1 | – | 1 | 4.2 |

| Request | Op | Reason | Count | Per min | SMB cost (rough) |
|---|---|---|---|---|---|
| load | stat | load: checking | 60 | 253.1 | CREATE/QUERY_INFO (or cached) |
| load | stat | load: before read | 22 | 92.8 | CREATE/QUERY_INFO (or cached) |
| load | read | load: read | 19 | 80.2 | CREATE + READ×n + CLOSE |
| load | stat | load: after read | 19 | 80.2 | CREATE/QUERY_INFO (or cached) |
| load | scandir | load: listing | 3 | 12.7 | CREATE + QUERY_DIRECTORY×n + CLOSE |
| load | stat | folder mtime | 3 | 12.7 | CREATE/QUERY_INFO (or cached) |
| list | lstat | listing: marker | 1 | 4.2 | CREATE/QUERY_INFO (or cached) |
| list | scandir | listing | 1 | 4.2 | CREATE + QUERY_DIRECTORY×n + CLOSE |

Most repeated:

| Op | Path | Times |
|---|---|---|
| stat | /share/2026/10/19/stuck/d_txy_forc9999.txt | 6 |
| stat | /share/2026/10/19/stuck/d_txy_forc1.txt | 5 |
| stat | /share/2026/10/19/stuck/d_txy_forc2.txt | 5 |
| stat | /share/2026/10/19/stuck/d_txy_forc3.txt | 5 |
| stat | /share/2026/10/19/stuck/d_txy_forc4.txt | 5 |
| stat | /share/2026/10/19/stuck/d_txy_forc5.txt | 5 |
| stat | /share/2026/10/19/stuck/d_txy_forc6.txt | 5 |
| stat | /share/2026/10/19/stuck/d_txy_forc7.txt | 5 |

## Files touched while the fake writer was writing them

| Op | Reason | Request | File | t |
|---|---|---|---|---|
| stat | live: new file | live | d_txy_forc1004.txt | 1792403367.02 |
| stat | live: new file | live | d_txy_forc1004.txt | 1792403370.04 |
| stat | live: new file | live | d_txy_forc1004.txt | 1792403373.53 |
| stat | live: new file | live | d_txy_forc1009.txt | 1792403396.10 |
| stat | live: new file | live | d_txy_forc1009.txt | 1792403399.50 |
| stat | live: last row | live | d_txy_forc1009.txt | 1792403399.50 |
| read_tail | live: last row | live | d_txy_forc1009.txt | 1792403399.50 |
| stat | load: checking | load | d_txy_forc2001.txt | 1792403501.86 |
| stat | load: before read | load | d_txy_forc2001.txt | 1792403501.87 |
| read | load: read | load | d_txy_forc2001.txt | 1792403501.87 |
| stat | load: after read | load | d_txy_forc2001.txt | 1792403501.88 |
| stat | load: verifying | load | d_txy_forc2001.txt | 1792403501.88 |
| stat | cache save: verifying | load | d_txy_forc2001.txt | 1792403501.88 |

## Operations on files modified under 5 s before (by the mtime they saw)

| Op | Reason | Request | Count | Youngest age (s) |
|---|---|---|---|---|
| stat | live: new file | live | 21 | 0.02 |
| stat | load: checking | load | 1 | 1.20 |

## GUI-process source calls (scenarios.py's hook)

None.

