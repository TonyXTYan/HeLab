#!/bin/bash
# usage: suite.sh <loops> <pytest args...>: the full suite, CI's flags but no reruns
set -u
mkdir -p /work && cd /work && tar xzf /in/src.tgz 2>/dev/null
. /venv/bin/activate
uv pip install --no-deps -e . >/dev/null 2>&1
loops=$1; shift
for k in $(seq 1 $loops); do
  timeout 1500 python -m pytest -n 4 -p no:cacheprovider --timeout=120 --timeout-method=thread "$@" > /out/suite-$k.txt 2>&1
  echo "k$k rc=$?" >> /out/summary.txt
done
