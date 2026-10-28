#!/bin/bash
# Stage 2's final timing run, serially, one backend at a time (brief step 4).
#   cd <floor root>; bash .ai/sessions/2026-10-29-claude-txy-bench/run_all.sh
# Writes timing/runs.jsonl, timing/first_call.jsonl, timing/time_large.log, timing/machine.txt and
# timing/run.log in this folder. Takes about 30 minutes.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
source venv/bin/activate
source .ai/local/floor-env.sh
export NUMBA_CACHE_DIR="$PWD/.ai/temp/txy/numba-cache"
S=.ai/sessions/2026-10-29-claude-txy-bench
T=$S/timing
mkdir -p "$T"
REPEATS=${REPEATS:-3}
BACKENDS=${BACKENDS:-"reference numpy numba cython rust mlx"}

{
  echo "date: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "model: $(sysctl -n hw.model) / $(sysctl -n machdep.cpu.brand_string)"
  echo "cores: $(sysctl -n hw.ncpu) ($(sysctl -n hw.perflevel0.physicalcpu) performance + $(sysctl -n hw.perflevel1.physicalcpu) efficiency)"
  echo "memory: $(( $(sysctl -n hw.memsize) / 1000000000 )) GB"
  echo "macOS: $(sw_vers -productVersion) ($(sw_vers -buildVersion)), $(uname -sr)"
  echo "power: $(pmset -g batt | head -1)"
  echo "python: $(python -c 'import sys; print(sys.version.split()[0])'), numpy $(python -c 'import numpy; print(numpy.__version__)')"
  echo "packages: $(uv pip list --python venv/bin/python 2>/dev/null | grep -iE '^(numba|llvmlite|mlx|mlx-metal|cython|maturin|helab-convert-rs) ' | tr -s ' ' | paste -sd ';' -)"
  echo "commit: $(git rev-parse --short HEAD)"
  echo "uptime: $(uptime)"
  # The brief's pgrep -fl "HeLab|helab" matches every process with a HeLab folder in its path (shells,
  # this run's own Python); the GUI is HeLab.app, venv/bin/helab or python -m helab.
  echo "helab GUI running: $(pgrep -fl 'HeLab.app/Contents/MacOS|bin/helab( |$)|-m helab' | grep -v pgrep || echo none)"
  echo "processes matching HeLab|helab (any path): $(pgrep -f 'HeLab|helab' | wc -l | tr -d ' ')"
  echo "top CPU: $(ps -Ao pcpu,comm -r | sed -n 2,6p | tr -s ' ' | paste -sd ';' -)"
} > "$T/machine.txt"
cat "$T/machine.txt"

log() { echo "$*" | tee -a "$T/run.log"; }
bench() { python "$S/bench.py" --out "$T/runs.jsonl" "$@" | tee -a "$T/run.log"; }

log "== first call $(uptime)"
python "$S/first_call.py" --repeats "$REPEATS" --backends $BACKENDS --out "$T/first_call.jsonl" | tee -a "$T/run.log"

for b in $BACKENDS; do
  log "== $b $(uptime)"
  for r in $(seq 1 "$REPEATS"); do bench --backend "$b" --mode serial --repeat "$r"; done
  for r in $(seq 1 "$REPEATS"); do bench --backend "$b" --mode serial --profile matlab-2023-lab-edit --repeat "$r"; done
  for w in 1 2 4 8 12 16; do
    for r in $(seq 1 "$REPEATS"); do bench --backend "$b" --mode processes-warm --workers "$w" --repeat "$r"; done
  done
  for w in 1 4 12; do
    for r in $(seq 1 "$REPEATS"); do bench --backend "$b" --mode processes-cold --workers "$w" --repeat "$r"; done
  done
  if [ "$b" != reference ] && [ "$b" != mlx ]; then
    for w in 1 4 8; do
      for r in $(seq 1 "$REPEATS"); do bench --backend "$b" --mode threads --workers "$w" --repeat "$r"; done
    done
  fi
  for w in 2 4 8; do
    for r in $(seq 1 "$REPEATS"); do bench --backend "$b" --mode within-shot --workers "$w" --shots large --repeat "$r"; done
  done
  copies=10; [ "$b" = reference ] && copies=2
  for r in $(seq 1 "$REPEATS"); do
    echo "-- time_large $b r$r copies $copies load $(sysctl -n vm.loadavg)" >> "$T/time_large.log"
    python .ai/sessions/2026-10-29-claude-txy-numpy/time_large.py --backend "$b" --copies "$copies" \
      --workers 2 4 8 | tee -a "$T/time_large.log" "$T/run.log"
  done
done
log "== done $(uptime)"
