"""Run every test suite for Bipbop.

    .venv\\Scripts\\python.exe tests\\run_all.py

Runs the logic tests (Python + Node) and the static web checks, and prints a
one-line summary per suite. Exit code is non-zero if anything failed.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

PYTESTS = ["test_tutor.py", "test_desktop.py", "test_run.py", "check_web.py"]
NODETESTS = ["test_core.mjs"]

results = []


def run(label, cmd, cwd, need=None):
    print(f"\n===== {label} =====")
    if need and not os.path.exists(need):
        print(f"  skipped ({os.path.basename(need)} not found)")
        results.append((label, "skip"))
        return
    proc = subprocess.run(cmd, cwd=cwd)
    results.append((label, "ok" if proc.returncode == 0 else "FAIL"))


for name in PYTESTS:
    run(name, [PY, os.path.join(HERE, name)], HERE)

for name in NODETESTS:
    run(name, ["node", os.path.join(HERE, name)], HERE)

print("\n===== summary =====")
bad = 0
for label, state in results:
    print(f"  {state:4} {label}")
    if state == "FAIL":
        bad += 1
print(f"\n{len(results) - bad}/{len(results)} suites passed")
sys.exit(1 if bad else 0)
