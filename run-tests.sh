#!/bin/sh
# Every suite, and a skip is not a pass.
#
# The media suite skips itself where ffmpeg is absent, which on a CI box that
# was supposed to have ffmpeg would read as green while testing nothing. So
# --strict refuses any skip.
set -eu

strict=${1:-}
fail=0

for suite in tests/test_contract.py tests/test_media.py; do
  echo "== $suite"
  out=$(PYTHONPATH=src python "$suite" 2>&1) || fail=1
  echo "$out" | tail -3
  if [ "$strict" = "--strict" ] && echo "$out" | grep -q "skipped="; then
    echo "STRICT: $suite skipped tests -- $(echo "$out" | grep -o 'skipped=[0-9]*')"
    fail=1
  fi
done

echo "== mutation"
PYTHONPATH=src python scripts/mutate.py || fail=1

[ "$fail" -eq 0 ] || { echo; echo "FAILED"; exit 1; }
echo; echo "all green"
