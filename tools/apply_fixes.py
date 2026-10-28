"""main.py apply: write chosen ready fixes from a review report into the file.

Run only by a human; no agent can call it (it is not in the registry). Nothing
is written unless every check passes on a combined copy in WORK_DIR first, and
nothing is ever committed.
"""

import difflib
import json
from pathlib import Path

import reports
from tools.patch_tools import apply_changes
from tools.verify_tools import failed_checks, rescan, run_behavior_tests
from tools.workspace import create_combined_copy, remove_copy, resolve_in_project


def apply_report(report_path, ids):
    """Returns {"ok": True, "file", "ids", "diff"} or {"ok": False, "reason"}."""
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _refuse(f"cannot read the report {report_path}")
    cards = {card["id"]: card for card in report.get("cards", [])}
    if not ids:
        return _refuse("no ids were chosen")
    for card_id in ids:
        if card_id not in cards:
            return _refuse(f"{card_id} is not in the report")
        if cards[card_id]["status"] != "ready":
            return _refuse(f"{card_id} is not ready (status {cards[card_id]['status']})")
    chosen = sorted((cards[card_id] for card_id in ids), key=lambda card: card["change"]["start_line"])

    source = resolve_in_project(report["file"])
    if source is None or not source.is_file():
        return _refuse(f"{report['file']} is not a file inside the project")
    if reports.file_sha256(source) != report["sha256"]:
        return _refuse("the file changed since the review (its sha256 differs from the report)")
    for earlier, later in zip(chosen, chosen[1:]):
        if later["change"]["start_line"] <= earlier["change"]["end_line"]:
            return _refuse(f"{earlier['id']} and {later['id']} change overlapping lines")

    change = apply_changes(source, [(c["change"]["start_line"], c["change"]["end_line"], c["change"]["replacement"])
                                    for c in chosen])
    if not change["ok"]:
        return _refuse(f"the changes cannot be applied together: {change['error']}")

    problems = _check_combined(report["file"], chosen)
    if problems:
        return _refuse("the combined copy failed its checks: " + "; ".join(problems))
    if reports.file_sha256(source) != report["sha256"]:  # changed while the checks ran
        return _refuse("the file changed during the checks")

    source.write_text("".join(change["patched"]), encoding="utf-8", newline="")
    diff = "".join(difflib.unified_diff(change["lines"], change["patched"],
                                        fromfile=f"a/{report['file']}", tofile=f"b/{report['file']}"))
    return {"ok": True, "file": report["file"], "ids": [c["id"] for c in chosen], "diff": diff}


def _check_combined(file_path, chosen):
    """rescan, ALL works tests and the attack tests of the chosen rules, on one copy with every change."""
    fixes = [({"rule": c["rule"], "line": c["line"], "sources": c.get("sources", [])}, c["change"]) for c in chosen]
    copy = create_combined_copy(file_path, fixes)
    if not copy["ok"]:
        return [f"could not make the combined copy: {copy['error']}"]
    try:
        scan = rescan(copy["copy_id"])
        tests = run_behavior_tests(copy["copy_id"])
    finally:
        remove_copy(copy["copy_id"])
    checks = {"closed": None, "new_findings": None, "works": "not_run", "attack": "not_run", "errors": []}
    for name, result in (("rescan", scan), ("run_behavior_tests", tests)):
        if not result["ok"]:
            checks["errors"].append(f"{name}: {result['error']}")
    if scan["ok"]:
        checks["closed"], checks["new_findings"] = scan["closed"], scan["new_findings"]
    if tests["ok"]:
        checks["works"], checks["attack"] = tests["works"], tests["attack"]
    return failed_checks(checks)


def _refuse(reason):
    return {"ok": False, "reason": reason}
