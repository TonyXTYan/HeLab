#!/bin/bash
# MATLAB's converter timed like the backends (bench_matlab.py), then numpy, cython and the reference
# again in the same window, so the comparison shares the machine's load.
#   bash .ai/sessions/2026-10-30-claude-matlab-bench/run.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
source venv/bin/activate
export HELAB_DIR_CACHES_OVERRIDE="$PWD/.ai/temp/matlab-bench-env/caches"
export HELAB_DIR_TEMPS_OVERRIDE="$PWD/.ai/temp/matlab-bench-env/temps"
export HELAB_APP_DIR_OVERRIDE="$PWD/.ai/temp/matlab-bench-env/app"
mkdir -p "$HELAB_DIR_CACHES_OVERRIDE" "$HELAB_DIR_TEMPS_OVERRIDE" "$HELAB_APP_DIR_OVERRIDE"
S=.ai/sessions/2026-10-30-claude-matlab-bench
mkdir -p "$S/timing"
{
  echo "date: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "model: $(sysctl -n hw.model) / $(sysctl -n machdep.cpu.brand_string)"
  echo "cores: $(sysctl -n hw.ncpu) ($(sysctl -n hw.perflevel0.physicalcpu) performance + $(sysctl -n hw.perflevel1.physicalcpu) efficiency)"
  echo "macOS: $(sw_vers -productVersion), MATLAB R2025b"
  echo "python: $(python -c 'import sys; print(sys.version.split()[0])'), numpy $(python -c 'import numpy; print(numpy.__version__)')"
  echo "commit: $(git rev-parse --short HEAD)"
  echo "uptime: $(uptime)"
} > "$S/timing/machine.txt"
REPEATS=${REPEATS:-3}
python "$S/bench_matlab.py" --variant 2019 --single --repeats "$REPEATS"
python "$S/bench_matlab.py" --variant 2019 --repeats "$REPEATS"
python "$S/bench_matlab.py" --variant 2023 --single --repeats "$REPEATS"
for b in ${BACKENDS:-numpy cython reference}; do
  for i in $(seq "$REPEATS"); do
    python .ai/sessions/2026-10-29-claude-txy-bench/bench.py --backend "$b" --mode serial --out "$S/timing/backends.jsonl"
  done
done
echo "uptime after: $(uptime)" >> "$S/timing/machine.txt"
