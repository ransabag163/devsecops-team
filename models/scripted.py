"""Rule-based models: fixed if/else decisions, no AI and no API.

ScriptedPenTesterModel trusts every rule match. Judging the context of a
finding is what the real model adds in step 2.

ScriptedDeveloperModel only fixes hardcoded_secret and skips the rest.

ScriptedTesterModel runs both checks and approves only if all of them passed.
"""

import ast

from models.base import DecisionModel
from tools.verify_tools import collect_checks, failed_checks


class ScriptedPenTesterModel(DecisionModel):
    def decide(self, state):
        file_path = state.get("file_path")
        observations = state.get("observations", [])

        if not file_path:
            return {"kind": "clarify", "text": "Which Python file should I check?"}

        if not observations:
            return {"kind": "tool", "name": "analyze_code", "args": {"file_path": file_path}}

        last = observations[-1]
        if not last.get("ok"):
            return {
                "kind": "final",
                "text": f"Could not analyze the file: {last.get('error')}",
                "report": {"findings": [], "error": last.get("error")},
            }

        findings = [
            {**f, "verdict": "real", "reason": "rule match"}
            for f in last["findings"]
        ]
        return {
            "kind": "final",
            "text": f"Found {len(findings)} finding(s).",
            "report": {"findings": findings, "error": None},
        }


MAX_IMPORT_DISTANCE = 15  # make_diff accepts at most 15 original lines


class ScriptedDeveloperModel(DecisionModel):
    """Step 1: read the code. Step 2: ask make_diff for the fix. Step 3: final."""

    def decide(self, state):
        file_path = state["file_path"]
        finding = state["finding"]
        observations = state.get("observations", [])
        line = finding["line"]

        if finding["rule"] != "hardcoded_secret":
            return _skip(finding, f"The scripted developer only fixes hardcoded_secret, not {finding['rule']}.")

        if not observations:
            return {"kind": "tool", "name": "read_snippet",
                    "args": {"file_path": file_path, "start_line": 1, "end_line": line}}

        if len(observations) == 1:
            snippet = observations[0]
            if not snippet.get("ok") or snippet["end_line"] < line:
                return _skip(finding, "Could not read the code up to the finding line.")
            plan = _plan_secret_fix(_snippet_lines(snippet["snippet"]), line)
            if isinstance(plan, str):
                return _skip(finding, plan)
            start, replacement = plan
            return {"kind": "tool", "name": "make_diff",
                    "args": {"file_path": file_path, "start_line": start, "end_line": line,
                             "replacement": replacement}}

        diff = observations[-1]
        if not diff.get("ok"):
            return _skip(finding, f"make_diff failed: {diff.get('error')}")
        args = state["actions"][-1]["args"]
        return {
            "kind": "final",
            "text": "Proposed a fix.",
            "proposal": {
                "finding_id": finding["id"],
                "status": "proposed",
                "start_line": args["start_line"],
                "end_line": args["end_line"],
                "replacement": args["replacement"],
                "explanation": "Read the secret from an environment variable instead of the source code.",
            },
        }


def _skip(finding, explanation):
    return {
        "kind": "final",
        "text": "Skipped.",
        "proposal": {"finding_id": finding["id"], "status": "skipped", "explanation": explanation},
    }


def _snippet_lines(snippet):
    """'5: code' lines -> {5: 'code'}"""
    lines = {}
    for row in snippet.splitlines():
        number, _, code = row.partition(": ")
        lines[int(number)] = code
    return lines


def _plan_secret_fix(lines, line):
    """Return (start_line, replacement) for one hunk, or a reason string to skip."""
    code = lines[line]
    indent = code[: len(code) - len(code.lstrip())]
    try:
        node = ast.parse(code.strip()).body[0]
    except (SyntaxError, IndexError):
        return "The finding line is not a simple assignment."
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return "The finding line is not a simple assignment."
    target = node.targets[0]
    name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", None)
    if not name:
        return "The finding line is not a simple assignment."

    fixed = f'{indent}{ast.unparse(target)} = os.environ.get("{name.upper()}", "")'
    if any(_imports_os(text) for n, text in lines.items() if n < line):
        return line, fixed

    # "import os" is missing: add it in the same hunk, just above the last import.
    import_lines = [n for n, text in lines.items() if n < line and text.startswith(("import ", "from "))]
    if import_lines and line - import_lines[-1] + 1 <= MAX_IMPORT_DISTANCE:
        start = import_lines[-1]
        kept = [lines[n] for n in range(start, line)]
        return start, "\n".join(["import os"] + kept + [fixed])
    if not import_lines and not indent:
        return line, "import os\n" + fixed
    return "Adding 'import os' would need a second change far from the finding."


def _imports_os(text):
    try:
        node = ast.parse(text.strip()).body[0]
    except (SyntaxError, IndexError):
        return False
    return isinstance(node, ast.Import) and any(alias.name == "os" for alias in node.names)


class ScriptedTesterModel(DecisionModel):
    """Step 1: rescan. Step 2: behavior tests. Step 3: approve, or retry with what failed."""

    def decide(self, state):
        copy_id = state["copy_id"]
        observations = state.get("observations", [])

        if len(observations) == 0:
            return {"kind": "tool", "name": "rescan", "args": {"copy_id": copy_id}}
        if len(observations) == 1:
            return {"kind": "tool", "name": "run_behavior_tests", "args": {"copy_id": copy_id}}

        problems = failed_checks(collect_checks(state["actions"], observations, copy_id))
        verification = {"finding_id": state["finding"]["id"], "verdict": "approve", "feedback": ""}
        if problems:
            verification.update(verdict="retry", feedback="Fix these checks: " + "; ".join(problems) + ".")
        return {"kind": "final", "text": f"Verdict: {verification['verdict']}.", "verification": verification}
