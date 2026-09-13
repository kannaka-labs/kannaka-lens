#!/bin/sh
# Every suite, discovered not listed, and a skip is not a pass.
#
# Two traps this avoids:
#
#   * a hardcoded suite list. The suites are globbed, because a list means a new
#     test file silently never runs -- kannaka-radio shipped that bug and needed
#     a guard test to catch it. Here the glob IS the guard.
#   * a skip reading as green. The media and perception suites skip themselves
#     where ffmpeg or the kannaka binary is absent, so on a box that was meant to
#     have them a green run would prove nothing. --strict refuses any skip.
set -eu

strict=${1:-}
fail=0
found=0

# --integration runs the suites that need the kannaka binary. They FAIL rather
# than skip when it is absent, so this mode cannot come back green having tested
# nothing.
if [ "$strict" = "--integration" ]; then
  for suite in tests/integration_*.py; do
    [ -f "$suite" ] || continue
    echo "== $suite"
    # Capture, THEN test the status. `python ... | tail` reports tail's exit
    # code, so `|| fail=1` on a pipeline never fires and a failing suite prints
    # green -- which is exactly what this runner caught itself doing.
    out=$(PYTHONPATH=src python "$suite" 2>&1) || fail=1
    echo "$out" | tail -4
  done
  [ "$fail" -eq 0 ] || { echo; echo "FAILED"; exit 1; }
  echo; echo "integration green"
  exit 0
fi

for suite in tests/test_*.py; do
  [ -f "$suite" ] || continue
  found=$((found + 1))
  echo "== $suite"
  out=$(PYTHONPATH=src python "$suite" 2>&1) || fail=1
  echo "$out" | tail -3
  if [ "$strict" = "--strict" ] && echo "$out" | grep -q "skipped="; then
    echo "STRICT: $suite $(echo "$out" | grep -o 'skipped=[0-9]*') -- a skipped suite is not a pass"
    fail=1
  fi
done

# Zero suites would otherwise be the quietest possible green.
if [ "$found" -eq 0 ]; then
  echo "no test suites found under tests/ -- that is a failure, not a pass"
  exit 1
fi
echo "== suites run: $found"

echo "== mutation"
PYTHONPATH=src python scripts/mutate.py || fail=1

[ "$fail" -eq 0 ] || { echo; echo "FAILED"; exit 1; }
echo; echo "all green"
