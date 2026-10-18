# Saved status after SMB remount

Tony saw saved folder-status icons appear at startup, then disappear as HeLab
rechecked folders. The old cache keyed summaries, derived statuses, and scan
failure history by path plus `(st_dev, st_ino)`. A read-only copy of the local
SQLite cache compared with the currently mounted folders showed device-only
identity differences for 357 accessible summaries and 35 accessible subtree
records. The old two-step browse first displayed saved statuses, then its
details pass rejected them when `st_dev` differed. The same identity reset could
clear blocked scan-failure history.

The fix removes device/inode checks from status metadata. Old identity fields
remain readable and are ignored; no cache clear or migration rewrite is needed.
Saved statuses remain as last-known results until the folder's own
status check replaces them. An observed mtime differing by at least two seconds
from the saved mtime marks a status possibly outdated. An incomplete child
listing retains a saved derived status and marks it outdated if a child checked
this session contradicts it. Scan-failure suppression survives remounts.
Dataset reuse keeps its separate TXY filename, size, mtime and missing-shot
checks.

Validation: `pytest -q -n 12 --reruns 5 --reruns-delay 1` passed with 746
passed, 1 skipped, 2 expected failures and no reruns. Strict mypy for `helab/`
and `tests`, Pyright for `helab tests`, and `git diff --check` passed. Terminal
#4 reviewed the live diff independently and found no blocker; its low-severity
tooltip, subtree-mtime and partial-listing findings were addressed with code
and tests. A native GUI restart on `/Volumes/dld_output` remains pending.

Follow-up finding: macOS assigns suffixes such as
`/Volumes/example-server-1` by mount order. During the read-only investigation,
one suffix mapped to a different share than before; a later mount can swap them
again. The initial path-keyed change could show another share's saved
summary, blocked history, preference or dataset record, sometimes without an
amber clock.

The helpers now capture the OS mount table when opening the store. `CacheStore`
translates each mounted SMB path to an `smb://server/share/relative`
key for summaries, subtrees, histories, preferences, datasets, pending saves and
save guards. Source filesystem operations and GUI navigation still use the OS
path. Admin results translate current share keys back to the active mount path.
There is no compatibility reader or migration for records keyed by older
`/Volumes/...-N` paths or account-qualified SMB URLs from interim builds.
For a fresh store, quit HeLab and move `store-v2` from the active cache
directory to the Trash before first launching this build. Alternatively, in
the new build dismiss old pending-save prompts with Don't cache, then Clear all
and clear Folder preferences separately. Until then, old records remain in the
inventory and pending-save prompts, even though new SMB lookups do not use them.
Visited folders get new records when their normal details/load check
completes; untouched child statuses require their own check (automatic visible
scanning may be off). Any old folder-specific preference must be set again for
the now identified share. An older HeLab build
sharing this store can still run its old identity logic.

Tests simulate two shares swapping mount suffixes and verify isolation and
restoration of summaries, subtrees, histories, preferences, datasets and pending
saves. Terminal #4's read-only review found Windows path
casing, mount lookup failure, unresolved nested mounts and UNC percent-name
issues. A short second review confirmed those fixes and found a UNC separator
edge case and a misleading parent warning, both addressed. Helpers now avoid
disk cache access when the mount source is unknown;
listing, details and batched subtree saves skip only affected children. Windows
mapped drives use direct Windows network APIs instead of querying every volume,
and direct UNC paths use the same share key. Focused tests cover those paths.
After the clean-slate simplification and reviewer fixes, the full suite passed
with 767 passed, 1 skipped, 2 expected failures and no reruns. Strict mypy for
`helab/` and `tests`, Pyright and `git diff --check` passed. Native
remount, GUI and Windows mapped-drive checks remain open.

Tony chose a clean-slate switch rather than legacy handling. Settings → Cache →
Clear all clears datasets, summaries, histories, subtrees and pending saves in
either build; Folder preferences has its own Clear action. The in-app clear
leaves epochs, meta and retired files (reclaimed by a later sweep), so moving
`store-v2` while HeLab is closed gives a fully fresh store. Old preferences are
keyed by the previous path scheme, so they will not automatically apply to new SMB keys.
Other lab PCs have their own caches and choices.
During a running app, `FolderCache` still keys RAM state by the
source path. Toolbar Refresh replaces saved results for the branches it relists;
a restart refreshes other paths and loaded data in other tabs. Share URLs include server
details and must stay local rather than enter shared results. Different SMB
accounts under the same OS login share cache rows; their access may differ.

The SMB cache key is local to one installation. It does not establish that a
local folder on one machine and a mounted share on another are equivalent, and
it does not synchronize cache rows. The network roadmap uses deliberate logical
root IDs, per-machine paths, validated input snapshots and service-delivered
remote metadata/results for that future feature.

## Toolbar Refresh and unsupported mounts

After a successful listing reads its saved records, toolbar Refresh resets
status, scan history, derived status and pending derived-status saves for the
root and expanded folders it relists, then accepts
the newly mounted share's saved records for each listed child even when its old
RAM record has a later date or revision. A failed listing, disabled cache or
cache read error retains the session's RAM status. Other tabs' rows repaint through the
shared cache signal. RAM datasets remain available but lose their recent-check
timestamp, so selection checks them against the source again. A background
details scan re-observes folder dates for freshness hints after replacement.
Paths outside the refreshed branches and loads that span a mount swap remain
for future work.
A details scan that read a folder before a subfolder was deleted can re-add
that row if it finishes after a newer listing; the next listing removes it.

Helpers report the mount type when disk caching is skipped for an unsupported
network volume. FolderCache remembers one warning per mount path per session;
the selected folder's tab/status line shows a short message and the tooltip
gives detail. Windows UNC and mapped paths with a WebDAV `host@SSL` server or
`DavWWWRoot` share are refused instead of getting SMB keys.

Validation after the review fixes: focused browse tests passed with 42
passed and 2 expected failures. The final full parallel suite passed with 767 passed,
1 skipped, 2 expected failures and no reruns. An intermediate full run exposed
a details ownership regression (6 failures, 30 reruns); it was fixed before the
clean final run. Strict mypy for `helab/` and `tests`, Pyright for `helab tests`,
and `git diff --check` passed. Native GUI,
actual remount and Windows checks remain on the manual list.
