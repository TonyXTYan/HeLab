#!/bin/bash
# usage: run.sh <loops> <pytest args...>
set -u
mkdir -p /work && cd /work && tar xzf /in/src.tgz 2>/dev/null
. /venv/bin/activate
uv pip install --no-deps -e . >/dev/null 2>&1
loops=$1; shift
for k in $(seq 1 $loops); do
  timeout 900 python -m pytest "$@" -p no:cacheprovider -o faulthandler_timeout=50 --timeout=60 --timeout-method=thread > /out/run-$k.txt 2>&1
  echo "k$k rc=$?" >> /out/summary.txt
done
