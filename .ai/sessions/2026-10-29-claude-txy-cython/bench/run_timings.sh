#!/bin/sh
# All 309 sample shots through stage 1's timing harness (dev/txy/time_samples.py), cython backend:
# serial, then across shots in processes and threads; the reference serially for comparison.
# Run from the checkout's root after `source venv/bin/activate; source .ai/local/floor-env.sh`.
out=.ai/sessions/2026-10-29-claude-txy-cython/bench/timings
set -e
uptime
python dev/txy/time_samples.py --positions all --backend cython --json $out/cython-serial.json
for workers in 4 8 12; do
  python dev/txy/time_samples.py --positions all --backend cython --parallelism processes --workers $workers --json $out/cython-processes-$workers.json
  python dev/txy/time_samples.py --positions all --backend cython --parallelism threads --workers $workers --json $out/cython-threads-$workers.json
done
python dev/txy/time_samples.py --positions all --backend cython --json $out/cython-serial-2.json
python dev/txy/time_samples.py --positions all --backend reference --json $out/reference-serial.json
uptime
