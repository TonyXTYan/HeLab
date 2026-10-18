# Shared folder and dataset reuse

Date: 2026-10-06
Baseline: GUI responsiveness checkpoint `54f79b1`.
Status: implemented; see `implementation.md` for validation and limits.

## Investigation and decision

- `status_cache` persists mutable StatusReport objects and legacy RAM badges. The new snapshot model intentionally avoids its disk reads during rendering.
- `os_file_system_cache` memoizes legacy filesystem operations on disk; it does not contain the new model's complete folder snapshots.
- Despite its name, `data_ram_cache` is a diskcache.FanoutCache containing Blosc-compressed pickled dictionaries. The isolated helper validates sorted TXY shot IDs, sizes and nanosecond modification timestamps before decompression. Keep this compatible disk format and existing legacy consumers.
- At the baseline, each FolderExplorer owned its own directory model and loaded arrays. The green `ram_opened` badge only described that tab. IOService deduplicated requests within one owner, not across tabs.
- The example scripts do not mutate shared loaded arrays. Development plotting reads dictionaries of arrays; arbitrary plugins may mutate inputs. Give each tab its own dictionary, share read-only arrays, and document `.copy()` for intentional modification.

Add an application-session memory cache associated with the existing IOService. Do not replace the legacy disk caches or perform filesystem access on the GUI thread.

## Implementation

1. Store completed folder snapshots separately from Qt tree nodes; reuse them with batched delivery. Keep per-tab selection and expansion. Reuse the last resolved default path within the session.
2. Use a 10-second freshness window on opening/selecting/expanding a cached folder. Older snapshots remain immediately usable while a shared helper checks for changes. Explicit refresh and deep recalculation bypass freshness.
3. Combine scan/load/resolve requests across subscribers. All subscribers receive the complete scan result in small batches; never publish failed or incomplete scans. Removing one subscriber must not cancel work needed by another.
4. Share loaded float64 arrays by folder/source signature. Publish a dataset atomically after successful loading. Read-only arrays prevent ordinary in-place changes from leaking between tabs; dictionaries remain private to each tab.
5. Broadcast completed refreshes and invalidation to interested tabs. Keep old displayed data when validation/loading fails. Reject obsolete helper results after invalidation and source changes. Clearing the disk cache also invalidates the shared memory entry.
6. Bound unused data with a 512 MiB memory budget, keeping datasets pinned by open tabs. Bound folder snapshot count and retained entry count. Evict unused entries first.
7. Green RAM badges reflect shared in-memory availability. Tooltip and footer distinguish cached content, checking for changes, loading data and failures. Preserve 16 px rows and the shared arc spinner.

## Verification

Test two tabs sharing one scan/load, array identity and mutation protection, fresh opening without helper work, expired background checks, explicit refresh propagation, cancellation by one subscriber, failure preserving old snapshots, invalidation rejecting late results, memory eviction/pinning, and actual helper/disk-cache compatibility. Run strict typing and the full suite. Actual stalled mounts and packaged builds remain manual release checks.
