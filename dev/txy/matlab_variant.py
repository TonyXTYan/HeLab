"""Run a MATLAB converter variant on copies of sample shots, for references the sample set lacks
(the 2023 lab edit's own output).

    python dev/txy/matlab_variant.py --variant 2023 [--positions even] [--limit 4] [--out DIR]

Copies each raw file to ``DIR/<set>/d<N>.txt`` (default ``.ai/temp/txy/matlab-<variant>``) and
runs MATLAB headless once over all of them; MATLAB writes ``d_txy_forc<N>.txt`` beside each copy
(the 2019 ``dld_raw_to_txy_counts`` writes none for an empty result). Never runs on the sample
set itself, and never writes into ``legacy/``. Check with
``check_samples.py --profile matlab-2023-lab-edit --reference-dir DIR``.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import subprocess
import sys

from _common import ROOT, TEMP, guard, sample_arguments

guard()

from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402

MATLAB = "/Applications/MATLAB_R2025b.app/bin/matlab"
VARIANTS = {
    "2019": (ROOT / "legacy/tdc_autoconverter/lib", "dld_raw_to_txy_counts"),
    "2023": (ROOT / "legacy/DLD_front_panel/lib/Core_BEC_Analysis/lib/import_mcp_tdc_data", "dld_raw_to_txy"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sample_arguments(parser)
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="2023")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    folder, function = VARIANTS[args.variant]
    out = (args.out or TEMP / f"matlab-{args.variant}").resolve()
    shots = select_shots(load_manifest(args.root), args.positions, args.sets)
    counted: dict[str, int] = defaultdict(int)
    calls = []
    for shot in shots:
        if args.limit is not None and counted[shot.set_name] >= args.limit:
            continue
        counted[shot.set_name] += 1
        target = out / shot.set_name
        target.mkdir(parents=True, exist_ok=True)
        (target / f"d{shot.shot}.txt").write_bytes(read_verified(shot.raw_path, shot.raw_sha256))
        (target / f"d_txy_forc{shot.shot}.txt").unlink(missing_ok=True)
        base = str(target / "d").replace("'", "''")
        calls.append(f"{function}('{base}',{shot.shot},{shot.shot});")
    script = out / "run_variant.m"
    script.write_text(f"addpath('{folder}');\n" + "\n".join(calls) + "\n")
    print(f"{len(calls)} shots into {out}; running MATLAB …", flush=True)
    done = subprocess.run([MATLAB, "-nodisplay", "-batch", f"run('{script}')"], cwd=out)
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
