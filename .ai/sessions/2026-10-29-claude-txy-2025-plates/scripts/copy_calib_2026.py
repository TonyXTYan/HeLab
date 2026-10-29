"""Copy a subset of the post-2025-swap data from X (read-only) to ~/HeLab-samples/calib-2026/ ONCE.

Writes manifest.json with each file's source path, size, mtime and SHA-256. Run once, then
`chmod -R a-w ~/HeLab-samples/calib-2026`.
"""
from __future__ import annotations
import hashlib, json, os, re, shutil, sys, time
from pathlib import Path

X = Path("/Volumes/192.168.137.1-4/dld_output_cheerypicked")
DEST = Path.home() / "HeLab-samples" / "calib-2026"
LIST = Path(sys.argv[1])  # folder of `stat -f "%z %m %N"` listings made beforehand


def listing(name: str) -> list[tuple[int, int, str]]:
    out = []
    for line in (LIST / f"{name}.txt").read_text().splitlines():
        size, mtime, path = line.split(" ", 2)
        out.append((int(size), int(mtime), path))
    return out


def shot(path: str) -> int:
    m = re.search(r"(\d+)\.txt$", path)
    return int(m.group(1)) if m else -1


def every(items: list, n: int) -> list:
    if n <= 0 or len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


plan: dict[str, list[str]] = {}
# Per-shot logs and the lab's analysis scripts (small).
for d in ("20260620_Rabi_trial_weak_intrap", "20260625_Ramsey_weak_trap", "20260626_Ramsey_weaktrap",
          "20260627_Ramsey_weaktrap"):
    plan.setdefault("logs", []).extend(p for _, _, p in listing(d) if not re.search(r"/d(_txy_forc)?\d+\.txt$", p))
# Every raw file of one Ramsey run: the full channel-7 series against the logs.
plan["ramsey-0625-raw"] = sorted((p for _, _, p in listing("20260625_Ramsey_weak_trap")
                                  if re.search(r"/d\d+\.txt$", p)), key=shot)
# Tight trap (raw + TXY): 6 shots from each raw subfolder.
tt = listing("20260722-tight-trap-freq-meas")
for sub in sorted({p.split("/")[1] for _, _, p in tt}):
    raws = sorted((p for _, _, p in tt if p.split("/")[1] == sub and re.search(r"/d\d+\.txt$", p)), key=shot)
    if raws:
        pick = every(raws, 6)
        plan.setdefault("tight-trap-raw", []).extend(pick)
        names = {p for _, _, p in tt}
        plan["tight-trap-raw"].extend(q for q in (p.replace("/d", "/d_txy_forc") for p in pick) if q in names)
# Pre-swap (2022 plates), Jan 2025: a few raw files and about.txt.
pre = sorted((p for _, _, p in listing("20250104_off_axis_check_mirror") if re.search(r"/d\d+\.txt$", p)), key=shot)
plan["preswap-2025-01-raw"] = every(pre, 6) + [p for _, _, p in listing("20250104_off_axis_check_mirror") if p.endswith("about.txt")]
# Collisions (halos): every TXY.
plan["collisions44-txy"] = sorted((p for _, _, p in listing("20261010-411trapcollisions44")), key=shot)
# RingBEC: every 10th TXY.
plan["ringbec-txy"] = every(sorted((p for _, _, p in listing("20260727-RingBEC")), key=shot), 100)
# Quantum efficiency: 3 per parameter subfolder, 6 of the top-level shots.
qe = listing("20260812_Quantum_efficiency")
for sub in sorted({p.split("/")[1] for _, _, p in qe if p.count("/") == 2}):
    plan.setdefault("qe-txy", []).extend(every(sorted((p for _, _, p in qe if p.split("/")[1] == sub and p.count("/") == 2), key=shot), 3))
plan["qe-txy"].extend(every(sorted((p for _, _, p in qe if p.count("/") == 1), key=shot), 6))

sizes = {p: s for d in ("20260620_Rabi_trial_weak_intrap", "20260625_Ramsey_weak_trap", "20260626_Ramsey_weaktrap",
                        "20260627_Ramsey_weaktrap", "20260722-tight-trap-freq-meas", "20250104_off_axis_check_mirror",
                        "20261010-411trapcollisions44", "20260727-RingBEC", "20260812_Quantum_efficiency")
         for s, _, p in listing(d)}
total = sum(sizes[p] for v in plan.values() for p in v)
print({k: (len(v), round(sum(sizes[p] for p in v) / 1e6, 1)) for k, v in plan.items()}, "total MB", total / 1e6)
if "--go" not in sys.argv:
    sys.exit(0)
assert total < 1.5e9
if DEST.exists():
    sys.exit(f"{DEST} exists: copy once only")
manifest = {"source_share": "//192.168.137.1/X (mounted /Volumes/192.168.137.1-4)", "source_root": "dld_output_cheerypicked",
            "copied": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "by": "Claude (session 2026-10-29-claude-txy-2025-plates)",
            "sets": {}}
for group, paths in plan.items():
    entries = []
    for p in paths:
        src = X / p
        dst = DEST / p
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        h = hashlib.sha256(dst.read_bytes()).hexdigest()
        st = src.stat()
        entries.append({"path": p, "bytes": st.st_size, "mtime": st.st_mtime, "sha256": h})
    manifest["sets"][group] = entries
    print(group, len(entries), flush=True)
(DEST / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
print("done")
