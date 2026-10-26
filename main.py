"""Run the pen_tester agent on one file.

Usage:
    .venv\\Scripts\\python.exe main.py samples/login.py [--model scripted|llm] [--trace]

Exit code: 0 = no real findings, 1 = at least one real finding,
           2 = error, or the run did not end in final.
"""

import argparse
import json
import sys

from agents.pen_tester import PenTester
from models.llm_pen_tester import LLMPenTesterModel
from models.scripted import ScriptedPenTesterModel

MODELS = {"scripted": ScriptedPenTesterModel, "llm": LLMPenTesterModel}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find security weaknesses in a Python file.")
    parser.add_argument("file_path", nargs="?", help="path to a .py file inside the project")
    parser.add_argument("--model", choices=MODELS, default="scripted", help="decision component (default: scripted)")
    parser.add_argument("--trace", action="store_true", help="also print the agent trace")
    args = parser.parse_args(argv)

    run = PenTester(MODELS[args.model]()).review(args.file_path)

    if run["status"] == "final":
        output = run["result"]
    else:
        output = {"status": run["status"], "message": run["result"]}
    print(json.dumps(output, indent=2, ensure_ascii=False))

    if args.trace:
        # The trace goes to stderr, so stdout stays clean JSON for scripts.
        print(json.dumps(run["trace"], indent=2, ensure_ascii=False), file=sys.stderr)

    return exit_code(run)


def exit_code(run):
    if run["status"] != "final" or run["result"]["status"] == "input_error":
        return 2
    if any(f["verdict"] == "real" for f in run["result"]["findings"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
