"""Run the pen_tester agent on one file.

Usage:
    .venv\\Scripts\\python.exe main.py samples/login.py [--trace]

Exit code: 0 = no findings, 1 = findings, 2 = input error (or the run did not finish).
"""

import argparse
import json
import sys

from agents.pen_tester import PenTester
from models.scripted import ScriptedPenTesterModel

EXIT_CODES = {"no_findings": 0, "findings": 1}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find security weaknesses in a Python file.")
    parser.add_argument("file_path", nargs="?", help="path to a .py file inside the project")
    parser.add_argument("--trace", action="store_true", help="also print the agent trace")
    args = parser.parse_args(argv)

    run = PenTester(ScriptedPenTesterModel()).review(args.file_path)

    if run["status"] == "final":
        output = run["result"]
    else:
        output = {"status": run["status"], "message": run["result"]}
    print(json.dumps(output, indent=2, ensure_ascii=False))

    if args.trace:
        # The trace goes to stderr, so stdout stays clean JSON for scripts.
        print(json.dumps(run["trace"], indent=2, ensure_ascii=False), file=sys.stderr)

    return EXIT_CODES.get(output["status"], 2)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
