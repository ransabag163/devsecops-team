"""Run the pen_tester agent on one file, and with --fix also the developer agent.

Usage:
    .venv\\Scripts\\python.exe main.py samples/login.py [--model scripted|llm] [--fix] [--trace]

Exit code: 0 = no real findings, 1 = at least one real finding,
           2 = error, a run that did not end in final, or (with --fix) a failed developer run.
"""

import argparse
import json
import sys

from agents.developer import Developer
from agents.pen_tester import PenTester
from models.llm_developer import LLMDeveloperModel
from models.llm_pen_tester import LLMPenTesterModel
from models.scripted import ScriptedDeveloperModel, ScriptedPenTesterModel

# Each agent gets its own model class; each LLM model uses its own provider.
MODELS = {
    "scripted": {"pen_tester": ScriptedPenTesterModel, "developer": ScriptedDeveloperModel},
    "llm": {"pen_tester": LLMPenTesterModel, "developer": LLMDeveloperModel},
}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find security weaknesses in a Python file.")
    parser.add_argument("file_path", nargs="?", help="path to a .py file inside the project")
    parser.add_argument("--model", choices=MODELS, default="scripted", help="decision component (default: scripted)")
    parser.add_argument("--fix", action="store_true", help="also ask the developer agent for fixes")
    parser.add_argument("--trace", action="store_true", help="also print the agent trace")
    args = parser.parse_args(argv)
    models = MODELS[args.model]

    run = PenTester(models["pen_tester"]()).review(args.file_path)
    if run["status"] == "final":
        findings_output = run["result"]
    else:
        findings_output = {"status": run["status"], "message": run["result"]}
    code = exit_code(run)

    if not args.fix:
        output, trace = findings_output, run["trace"]
    else:
        fix_run = None
        if code != 2:  # only fix findings from a pen_tester run that worked
            fix_run = Developer(models["developer"]()).fix(run["result"])
            if fix_run["status"] != "final" or fix_run["result"]["status"] == "input_error":
                code = 2
        output = {"findings_report": findings_output, "fix_report": fix_run and fix_run["result"]}
        trace = {"pen_tester": run["trace"], "developer": fix_run and fix_run["runs"]}

    print(json.dumps(output, indent=2, ensure_ascii=False))
    if args.trace:
        # The trace goes to stderr, so stdout stays clean JSON for scripts.
        print(json.dumps(trace, indent=2, ensure_ascii=False), file=sys.stderr)
    return code


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
