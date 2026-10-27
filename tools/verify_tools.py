"""The tester's tools. Both work on a patched copy in WORK_DIR and never touch the original.

- rescan:             run analyze_code on the copy and compare with the original
- run_behavior_tests: run the sample's works and attack tests on the copy
"""

import os
import shutil
import subprocess
import sys

import config
from tools.analyze_code import analyze_code
from tools.workspace import read_meta

# A finding of the same rule this close to the changed lines means the weakness is still there.
NEAR_LINES = 3
MAX_OUTPUT = 2000
# The only environment variables the patched code gets. It is untrusted, so no keys or tokens.
PASSED_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC")
HELPER_FILES = ("conftest.py", "behavior_helpers.py")


def rescan(copy_id):
    folder, meta = read_meta(copy_id)
    if folder is None:
        return {"ok": False, "error": "unknown_copy"}
    original = analyze_code(config.PROJECT_ROOT / meta["file"])
    patched = analyze_code(folder / meta["copy_file"])
    if not original["ok"]:
        return original
    if not patched["ok"]:
        return patched

    changes = meta["changes"]
    # closed only if every change closed its finding: the rule may not fire near the
    # changed lines or where the finding itself moved to.
    closed = all(_change_closed(change, changes, patched["findings"]) for change in changes)
    known = [(f["rule"], _new_lines(f["line"], changes)) for f in original["findings"]]
    new_findings = [
        {key: f[key] for key in ("rule", "cwe", "line", "evidence")}
        for f in patched["findings"]
        if not any(rule == f["rule"] and low <= f["line"] <= high for rule, (low, high) in known)
    ]
    return {"ok": True, "closed": closed, "new_findings": new_findings}


def _change_closed(change, changes, patched_findings):
    start, new_end = change["new_start_line"], change["new_end_line"]
    finding_low, finding_high = _new_lines(change["finding_line"], changes)
    return not any(
        f["rule"] == change["rule"]
        and (start - NEAR_LINES <= f["line"] <= new_end + NEAR_LINES or finding_low <= f["line"] <= finding_high)
        for f in patched_findings
    )


def _new_lines(line, changes):
    """Where an original line ended up in the copy, as a (low, high) range."""
    moved = line
    for change in changes:
        if change["start_line"] <= line <= change["end_line"]:
            # Inside a change: anywhere in its new lines.
            return change["new_start_line"], max(change["new_start_line"], change["new_end_line"])
        if line > change["end_line"]:
            moved += (change["new_end_line"] - change["new_start_line"] + 1) - (change["end_line"] - change["start_line"] + 1)
    return moved, moved


def run_behavior_tests(copy_id):
    folder, meta = read_meta(copy_id)
    if folder is None:
        return {"ok": False, "error": "unknown_copy"}
    name = meta["sample"]
    works_file = config.BEHAVIOR_DIR / f"test_{name}_works.py"
    attack_file = config.BEHAVIOR_DIR / f"test_{name}_attack.py"
    if not works_file.is_file() or not attack_file.is_file():
        return {"ok": True, "works": "not_available", "attack": "not_available", "output": ""}

    # The tests are copied next to the patched file, so pytest only sees the run folder.
    tests_dir = folder / "behavior"
    tests_dir.mkdir(exist_ok=True)
    for path in [config.BEHAVIOR_DIR / f for f in HELPER_FILES] + [works_file, attack_file]:
        shutil.copy(path, tests_dir / path.name)
    (folder / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    env = behavior_env(folder, folder / meta["copy_file"])
    works = _run_pytest(folder, env, [f"behavior/{works_file.name}"])
    # Only the attacks of the rules this copy is about (one rule, or the chosen rules for apply).
    attack = _run_pytest(folder, env, [f"behavior/{attack_file.name}", "-k", " or ".join(meta["rules"])])
    output = f"works:\n{works['output'][-MAX_OUTPUT // 2:]}\nattack:\n{attack['output'][-MAX_OUTPUT // 2:]}"
    return {"ok": True, "works": works["result"], "attack": attack["result"], "output": output[:MAX_OUTPUT]}


def behavior_env(folder, sample_path):
    """An allowlist environment: only what Python needs, never a copy of os.environ."""
    temp = folder / "tmp"
    temp.mkdir(exist_ok=True)
    env = {name: os.environ[name] for name in PASSED_ENV if name in os.environ}
    env.update({
        "TEMP": str(temp),
        "TMP": str(temp),
        "SAMPLE_UNDER_TEST": str(sample_path),
        "PYTHONDONTWRITEBYTECODE": "1",
        # No third-party pytest plugins (langgraph brings anyio and langsmith): faster and fewer moving parts.
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    })
    return env


def collect_checks(actions, observations, copy_id):
    """The latest result of each check on copy_id, taken from the tool observations only."""
    checks = {"closed": None, "new_findings": None, "works": "not_run", "attack": "not_run", "errors": []}
    for action, observation in zip(actions, observations):
        args = action.get("args")
        if not isinstance(args, dict) or args.get("copy_id") != copy_id:
            continue  # a check on another copy says nothing about this proposal
        if not observation.get("ok"):
            checks["errors"].append(f"{action.get('name')}: {observation.get('error')}")
        elif action.get("name") == "rescan":
            checks["closed"], checks["new_findings"] = observation["closed"], observation["new_findings"]
        elif action.get("name") == "run_behavior_tests":
            checks["works"], checks["attack"] = observation["works"], observation["attack"]
    return checks


def failed_checks(checks):
    """Every reason not to approve, as short sentences. Empty means all checks passed."""
    problems = list(checks["errors"])
    if checks["closed"] is None:
        problems.append("rescan did not run")
    elif not checks["closed"]:
        problems.append("rescan still finds the weakness in or near the changed lines")
    if checks["new_findings"]:
        found = ", ".join(f"{f['rule']} on line {f['line']}" for f in checks["new_findings"])
        problems.append(f"the fix adds new findings: {found}")
    for kind in ("works", "attack"):
        if checks[kind] != "passed":
            problems.append(f"{kind} tests: {checks[kind]}")
    return problems


def _run_pytest(folder, env, args):
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "-c", "pytest.ini", "--rootdir", ".", *args]
    try:
        done = subprocess.run(command, cwd=folder, env=env, capture_output=True, text=True,
                              timeout=config.BEHAVIOR_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"result": "failed", "output": f"timeout after {config.BEHAVIOR_TIMEOUT}s"}
    # pytest exit codes: 0 all passed, 5 no test matched (no attack test for this rule).
    result = {0: "passed", 5: "not_available"}.get(done.returncode, "failed")
    return {"result": result, "output": done.stdout + done.stderr}
