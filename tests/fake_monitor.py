"""Stand-in for pecron-monitor used by test_runner.py.

FAKE_PLAN names a JSON file holding a list of runs; each child start takes the
next one (counted in FAKE_PLAN + ".n"). A run is
{"lines": [...], "exit": int, "sleep": seconds, "on_term": "exit" | "ignore"}.
Lines are printed first, then the child sleeps, then exits.
"""

import json
import os
import signal
import sys
import time

plan_path = os.environ["FAKE_PLAN"]
counter = plan_path + ".n"
n = int(open(counter).read()) if os.path.exists(counter) else 0
with open(counter, "w") as f:
    f.write(str(n + 1))
runs = json.load(open(plan_path))
run = runs[min(n, len(runs) - 1)]

with open(plan_path + ".args", "w") as f:
    json.dump(
        {
            "args": sys.argv[1:],
            "env": {k: v for k, v in os.environ.items() if k.startswith(("PECRON_", "PYTHON"))},
        },
        f,
    )


def on_term(*_):
    if run.get("on_term", "exit") == "exit":
        print("12:00:00 INFO Bridge offline published", flush=True)
        sys.exit(0)


signal.signal(signal.SIGTERM, on_term)
for line in run.get("lines", []):
    print(line, flush=True)
deadline = time.monotonic() + run.get("sleep", 0)
while time.monotonic() < deadline:
    time.sleep(0.01)
sys.exit(run.get("exit", 0))
