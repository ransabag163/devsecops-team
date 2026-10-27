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

    start, new_end = meta["start_line"], meta["new_end_line"]
    closed = not any(
        f["rule"] == meta["rule"] and start - NEAR_LINES <= f["line"] <= new_end + NEAR_LINES
        for f in patched["findings"]
    )
    known = [(f["rule"], _new_lines(f["line"], meta)) for f in original["findings"]]
    new_findings = [
        {key: f[key] for key in ("rule", "cwe", "line", "evidence")}
        for f in patched["findings"]
        if not any(rule == f["rule"] and low <= f["line"] <= high for rule, (low, high) in known)
    ]
    return {"ok": True, "closed": closed, "new_findings": new_findings}


def _new_lines(line, meta):
    """Where an original line ended up in the copy, as a (low, high) range."""
    start, end, new_end = meta["start_line"], meta["end_line"], meta["new_end_line"]
    if line < start:
        return line, line
    if line > end:
        moved = line + new_end - end
        return moved, moved
    return start, max(start, new_end)  # inside the change: anywhere in the new lines


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
    attack = _run_pytest(folder, env, [f"behavior/{attack_file.name}", "-k", meta["rule"]])
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
    })
    return env


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
