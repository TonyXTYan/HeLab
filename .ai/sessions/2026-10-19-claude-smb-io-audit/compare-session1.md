| Phase | s | helpers (before → after) | listings (before → after) | stats (before → after) | marker opens (before → after) | reads (before → after) | tail reads (before → after) | icons (before → after) |
|---|---|---|---|---|---|---|---|---|
| S1 startup | 2 | 8 → **9** | 2 | 5 → **7** | 1 → **2** | 0 | 0 | 3 |
| S1 idle 60 s, tree open | 60 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| S1 expand 2026/10/18 and 19 | 2 | 9 | 8 | 18 | 0 | 0 | 0 | 10 |
| S1 select and load run_a (120 shots) | 1 | 3 | 2 | 602 → **482** | 0 | 120 | 0 | 0 |
| S1 select and load run_b (40 shots) | 1 | 2 | 2 | 202 → **162** | 0 | 40 | 0 | 0 |
| S1 reselect run_a within 10 s | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| S1 idle 15 s | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| S1 reselect run_b after 15 s (disk cached) | 1 | 1 | 0 | 6 | 0 | 0 | 0 | 0 |
| S1 second tab: RAM-only folder, load run_r | 2 | 7 | 4 | 485 | 0 | 120 | 0 | 2 |
| S1 tab switch 1 (to tab 1) after 15 s | 16 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| S1 tab switch 2 (to tab 2) after 15 s | 16 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| S1 tab switch 3 (to tab 1) after 15 s | 16 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| S1 tab switch 4 (to tab 2) after 15 s | 17 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| S1 toolbar Refresh | 2 | 11 | 10 | 22 | 1 | 0 | 0 | 13 |
| S1 right-click Retry / Refresh on run_b (shown) | 2 | 2 | 2 | 82 | 0 | 0 | 0 | 0 |
| S1 select and load run_live | 1 | 3 | 2 | 152 → **122** | 0 | 30 | 0 | 0 |
| S1 Live on, writer adds 12 shots every 4 s (1004 written over 7.5 s, 1009 pauses 4 s mid-file) † | 60 | 30 | 20 → **17** | 313 → **204** | 95 → **21** | 21 → **10** | 11 → **0** | 0 |
| S1 Live on, writer done: 15 s to settle | 15 | 5 → **6** | 2 | 21 → **25** | 10 → **2** | 1 → **2** | 1 → **0** | 0 |
| S1 Live on, nothing new, 60 s | 60 | 20 | 1 | 25 | 5 → **1** | 0 | 0 | 0 |
| S1 Live off (saves new shots) | 2 | 1 | 1 | 127 → **42** | 0 → **1** | 1 → **0** | 0 | 0 |
| S1 load run_stall while its new shot 2001 stalls 8 s mid-file (selected 6.5 s in) | 9 | 4 → **2** | 2 | 59 → **46** | 1 → **0** | 11 | 0 | 0 |
| S1 simulated mount change (a listing reports another mount table), 30 s | 30 | 803 → **2** | 0 | 828 → **2** | 414 → **1** | 0 | 0 | 0 |
| S1 a listing reports the real mount table again, 15 s | 16 | 4 → **2** | 2 | 9 → **7** | 1 → **0** | 0 | 0 | 0 |
| S1 select a folder that can't be listed (permission), 20 s | 20 | 2 | 1 | 1 | 0 | 0 | 0 | 0 |
| S1 select a folder whose file read hangs (timeouts 3/4/5 s), until it fails | 14 | 4 | 4 | 105 | 0 | 19 | 0 | 0 |
| S1 idle 60 s at the end | 60 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| S1 quit | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| S1 end | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

† Before: “S1 Live on, writer adds 12 shots every 4 s (1004 written over 7.5 s, 1009 stalls 8 s mid-file)”.
