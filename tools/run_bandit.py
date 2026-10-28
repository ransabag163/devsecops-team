"""Read-only Bandit scan of one Python file, for the pen_tester.

Bandit (https://bandit.readthedocs.io) only reads the code; it never runs it.
It runs in a subprocess with a timeout and an environment without keys, and
we keep only results with MEDIUM or HIGH severity AND MEDIUM or HIGH confidence.

Each result gets our finding shape: rule = the Bandit test id (for example
B307), the CWE Bandit gives, the line, and the same evidence and context as
analyze_code.
"""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import config
from tools.analyze_code import _context, _evidence  # the same evidence and context as analyze_code

LEVELS = ("MEDIUM", "HIGH")
# Bandit is trusted, but it still gets no keys: only what Python needs to start.
# LOCALAPPDATA is where stevedore (Bandit's plugin loader) keeps its cache; without it
# the cache path stays "~/AppData/Local" and is created inside the project folder.
PASSED_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "LOCALAPPDATA")
MAX_MESSAGE = 200


def run_bandit(file_path):
    path = Path(file_path)
    if not path.is_file():
        return {"ok": False, "error": "file_not_found"}
    if path.suffix.lower() != ".py":
        return {"ok": False, "error": "unsupported_language"}
    if path.stat().st_size > config.MAX_FILE_BYTES:
        return {"ok": False, "error": "file_too_large"}
    data = path.read_bytes()
    try:
        ast.parse(data, filename=str(path))
    except (SyntaxError, ValueError):
        return {"ok": False, "error": "syntax_error"}

    command = [sys.executable, "-m", "bandit", "-f", "json", "-q",
               "--severity-level", "medium", "--confidence-level", "medium", str(path)]
    env = {name: os.environ[name] for name in PASSED_ENV if name in os.environ}
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=config.BANDIT_TIMEOUT,
                              env=env, cwd=config.PROJECT_ROOT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    # Bandit exits with 0 when it found nothing and 1 when it found something.
    if done.returncode not in (0, 1):
        return {"ok": False, "error": "bandit_failed"}
    try:
        results = json.loads(done.stdout)["results"]
    except (ValueError, KeyError, TypeError):
        return {"ok": False, "error": "bandit_failed"}

    lines = data.decode("utf-8", errors="replace").splitlines()
    findings, seen = [], set()
    for result in sorted(results, key=lambda r: (r.get("line_number", 0), r.get("test_id", ""))):
        # Bandit filters too, but the application checks the levels itself.
        if result.get("issue_severity") not in LEVELS or result.get("issue_confidence") not in LEVELS:
            continue
        rule, line = result.get("test_id"), result.get("line_number")
        if not isinstance(rule, str) or type(line) is not int or (rule, line) in seen:
            continue
        seen.add((rule, line))
        cwe_id = (result.get("issue_cwe") or {}).get("id")
        findings.append({
            "rule": rule,
            "cwe": f"CWE-{cwe_id}" if cwe_id else "CWE-unknown",
            "line": line,
            "evidence": _evidence(lines, line),
            "context": _context(lines, line),
            "message": str(result.get("issue_text", ""))[:MAX_MESSAGE],
        })
    return {"ok": True, "findings": findings}
