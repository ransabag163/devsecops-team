"""Run the pen_tester agent on one file, with --fix also the developer agent,
and with --verify also the tester agent.

Usage:
    .venv\\Scripts\\python.exe main.py samples/login.py [--model scripted|llm] [--fix] [--verify] [--keep-work] [--trace]

Exit code: 0 = no real findings, 1 = at least one real finding,
           2 = error, a run that did not end in final, a failed developer or tester run,
               or the run deadline (config.RUN_DEADLINE_SECONDS) passed before the work was done.
"""

import argparse
import json
import sys

import config
from agents.developer import Developer
from agents.pen_tester import PenTester
from agents.tester import Tester
from deadline import Deadline
from models.llm_developer import LLMDeveloperModel
from models.llm_pen_tester import LLMPenTesterModel
from models.llm_tester import LLMTesterModel
from models.scripted import ScriptedDeveloperModel, ScriptedPenTesterModel, ScriptedTesterModel
from tools.workspace import remove_stale_copies

# Live trace lines start with this, so the full trace at the end is easy to find.
TRACE_PREFIX = "[trace] "

# Each agent gets its own model class; each LLM model uses its own provider.
MODELS = {
    "scripted": {"pen_tester": ScriptedPenTesterModel, "developer": ScriptedDeveloperModel,
                 "tester": ScriptedTesterModel},
    "llm": {"pen_tester": LLMPenTesterModel, "developer": LLMDeveloperModel, "tester": LLMTesterModel},
}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find security weaknesses in a Python file.")
    parser.add_argument("file_path", nargs="?", help="path to a .py file inside the project")
    parser.add_argument("--model", choices=MODELS, default="scripted", help="decision component (default: scripted)")
    parser.add_argument("--fix", action="store_true", help="also ask the developer agent for fixes")
    parser.add_argument("--verify", action="store_true", help="also check each fix with the tester agent (implies --fix)")
    parser.add_argument("--keep-work", action="store_true", help="keep the tester's run folders in .work/")
    parser.add_argument("--trace", action="store_true", help="also print the agent trace")
    args = parser.parse_args(argv)
    args.fix = args.fix or args.verify
    models = MODELS[args.model]
    deadline = Deadline(config.RUN_DEADLINE_SECONDS)
    not_done = []
    remove_stale_copies()  # run folders left over from a run that was stopped

    def prepare(agent):
        agent.deadline = deadline
        if args.trace:
            agent.on_step = print_step
        return agent

    run = prepare(PenTester(models["pen_tester"]())).review(args.file_path)
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
            fix_run = prepare(Developer(models["developer"]())).fix(run["result"])
            if fix_run["status"] != "final" or fix_run["result"]["status"] == "input_error":
                code = 2
            not_done += [f"developer: {finding_id}" for finding_id in fix_run["not_done"]]
        elif deadline.hit:
            not_done.append("developer: all findings")
        output = {"findings_report": findings_output, "fix_report": fix_run and fix_run["result"]}
        trace = {"pen_tester": run["trace"], "developer": fix_run and fix_run["runs"]}

        if args.verify:
            verify_run = None
            if fix_run is not None:  # check whatever proposals the developer made
                verify_run = prepare(Tester(models["tester"]())).verify(run["result"], fix_run["result"], args.keep_work)
                if verify_run["status"] != "final" or verify_run["result"]["status"] == "input_error":
                    code = 2
                not_done += [f"tester: {finding_id}" for finding_id in verify_run["not_done"]]
            elif deadline.hit:
                not_done.append("tester: all proposals")
            output["verification_report"] = verify_run and verify_run["result"]
            trace["tester"] = verify_run and verify_run["runs"]

    if deadline.hit:
        # Something was stopped or skipped because the whole run took too long.
        code = 2
        output = {**output, "run_deadline": {"seconds": deadline.seconds, "not_done": not_done}}

    print(json.dumps(output, indent=2, ensure_ascii=False))
    if args.trace:
        # The trace goes to stderr, so stdout stays clean JSON for scripts.
        print(json.dumps(trace, indent=2, ensure_ascii=False), file=sys.stderr)
    return code


def print_step(agent, finding_id, entry):
    """With --trace, print each step to stderr as soon as it happens, on one line."""
    line = {"agent": agent, "finding_id": finding_id, **entry}
    print(TRACE_PREFIX + json.dumps(line, ensure_ascii=False), file=sys.stderr, flush=True)


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
