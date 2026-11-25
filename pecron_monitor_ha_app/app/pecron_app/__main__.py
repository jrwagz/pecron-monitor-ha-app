"""Entry point: ``python3 -m pecron_app check|run``."""

import sys

from . import runner

COMMANDS = {"check": runner.check, "run": runner.run}

if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
    print("usage: python3 -m pecron_app check|run", file=sys.stderr)
    sys.exit(2)
sys.exit(COMMANDS[sys.argv[1]]())
