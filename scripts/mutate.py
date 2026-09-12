"""Mutation check for kannaka-lens's stage contract.

Each mutant breaks one behaviour the contract promises. A survivor means no
test checks that behaviour -- the defect class this repo exists to avoid: a
check weaker than what it checks.

Anchors are short and must match exactly once. An anchor that matches zero or
many times is reported as a problem, never as a pass. Multi-line anchors are
built with NL rather than escapes, because backslash escapes did not survive
being written through a shell heredoc.

Run from the repo root.
"""
import re
import subprocess
import sys
from pathlib import Path

SRC = Path("src/lens/contract.py")
TESTS = "tests/test_contract.py"
NL = chr(10)

MUTANTS = [
    ("essential is ignored when a need is unmet",
     "is essential and cannot run: {why}", "cannot run: {why}"),
    ("an essential stage that raises does not abort",
     "                raise StageAborted(f" + chr(34) + "{stage.name} is essential and failed",
     "                pass  # mutant" + NL + "                _ = (f"
     + chr(34) + "{stage.name} is essential and failed"),
    ("a degradation records no reason",
     '{"status": DEGRADED, "reason": why}', '{"status": DEGRADED}'),
    ("not-applicable is recorded as a failure",
     '{"status": NOT_APPLICABLE, "reason": str(exc)}', '{"status": FAILED, "reason": str(exc)}'),
    ("not-applicable is itemised as trouble",
     "TROUBLE = (DEGRADED, FAILED)", "TROUBLE = (DEGRADED, FAILED, NOT_APPLICABLE)"),
    ("dependencies are not checked at all",
     "for dep in stage.after:", "for dep in ():"),
    ("an unmet dependency passes the check",
     'if entry["status"] not in (OK, SKIPPED):', "if False:"),
    ("a finished stage is redone every time",
     'if prior and prior["status"] == OK and not force:', "if False:"),
    ("an n/a stage is treated as done and never retried",
     'prior["status"] == OK and not force',
     'prior["status"] in (OK, NOT_APPLICABLE) and not force'),
    ("the record is written once at the end instead of after each stage",
     "        flush()" + NL + '        log(f"  + {stage.name}',
     '        log(f"  + {stage.name}'),
    ("result() hands over output from a stage that did not succeed",
     'if not entry or entry["status"] not in (OK, SKIPPED):', "if False:"),
]

# The essential-raise mutant above leaves an unbalanced expression on purpose;
# replace it with a form that still parses.
MUTANTS[1] = (
    "an essential stage that raises does not abort",
    "raise StageAborted(f" + chr(34) + "{stage.name} is essential and failed: {detail}"
    + chr(34) + ") from exc",
    "detail = detail  # mutant: the abort is gone",
)

orig = SRC.read_text("utf-8")
problems = []
try:
    for label, find, repl in MUTANTS:
        n = orig.count(find)
        if n != 1:
            print("  ?? anchor matched %dx, mutant never applied: %s" % (n, label))
            problems.append(label)
            continue
        SRC.write_text(orig.replace(find, repl, 1), "utf-8")
        r = subprocess.run([sys.executable, TESTS], capture_output=True, text=True)
        if r.returncode == 0:
            print("  SURVIVED  " + label)
            problems.append(label)
        else:
            hit = sorted(set(re.findall(r"(?:FAIL|ERROR): (\w+)", r.stderr)))
            print("  killed    %s  <- %s" % (label, ", ".join(hit[:2]) or "error"))
finally:
    SRC.write_text(orig, "utf-8")

print()
if problems:
    print("%d of %d not killed: %s" % (len(problems), len(MUTANTS), "; ".join(problems)))
    sys.exit(1)
print("all %d mutants killed" % len(MUTANTS))
