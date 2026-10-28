"""Patched copies for the tester. Application code: the model cannot call these.

The application (not the model) applies a proposal to a copy in a fresh folder
WORK_DIR/run-<id>/, next to a meta.json that says what was changed. The
original file is never written. After the run the application removes only its
own run folder, and only after checking that it is inside WORK_DIR. On start
it also removes run folders left over from a run that was stopped (older than
STALE_RUN_SECONDS), with the same checks.
"""

import json
import re
import shutil
import time
import uuid
from pathlib import Path

import config
from tools.findings import rule_names
from tools.patch_tools import apply_changes

COPY_ID = re.compile(r"^run-[0-9a-f]{8}$")
META_FILE = "meta.json"


def create_copy(file_path, finding, proposal):
    """Apply one proposal to a copy of file_path. Returns {"ok": True, "copy_id": ...} or an error."""
    return create_combined_copy(file_path, [(finding, proposal)])


def create_original_copy(file_path, finding):
    """An unchanged copy of file_path, to show that the finding's attack works on the original."""
    return create_combined_copy(file_path, [], rules=[finding["rule"]])


def create_combined_copy(file_path, fixes, rules=None):
    """Apply several (finding, proposal) pairs to one copy. They may not overlap.

    meta.json lists each change with its old and new line numbers, so rescan can
    map lines, and the rules whose attack tests run on this copy.
    """
    source = resolve_in_project(file_path)
    if source is None:
        return {"ok": False, "error": "path_outside_project"}
    if fixes:
        change = apply_changes(source, [(p["start_line"], p["end_line"], p["replacement"]) for _, p in fixes])
        if not change["ok"]:
            return change
        text = "".join(change["patched"])
    elif source.is_file():
        text = source.read_bytes().decode("utf-8", errors="replace")
    else:
        return {"ok": False, "error": "file_not_found"}

    changes, delta = [], 0
    for finding, proposal in sorted(fixes, key=lambda fix: fix[1]["start_line"]):
        start, end = proposal["start_line"], proposal["end_line"]
        new_count = len(proposal["replacement"].splitlines())
        changes.append({
            "rule": finding["rule"], "finding_line": finding["line"], "start_line": start, "end_line": end,
            # Every name the finding has (analyze_code and Bandit), so rescan knows it under both.
            "rule_names": sorted(rule_names(finding)),
            "new_start_line": start + delta,
            # The last new line (new_start - 1 if the change only deletes lines).
            "new_end_line": start + delta + new_count - 1,
        })
        delta += new_count - (end - start + 1)

    copy_id = f"run-{uuid.uuid4().hex[:8]}"
    folder = Path(config.WORK_DIR) / copy_id
    folder.mkdir(parents=True)
    (folder / source.name).write_text(text, encoding="utf-8", newline="")
    meta = {
        "file": source.relative_to(config.PROJECT_ROOT.resolve()).as_posix(),
        "copy_file": source.name,
        "sample": source.stem,
        "rules": rules if rules is not None else [c["rule"] for c in changes],
        "changes": changes,
    }
    (folder / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"ok": True, "copy_id": copy_id}


def resolve_in_project(file_path):
    """The absolute path of file_path inside the project, or None if it points outside."""
    root = config.PROJECT_ROOT.resolve()
    path = (root / file_path).resolve()
    return path if path.is_relative_to(root) else None


def copy_folder(copy_id):
    """The run folder of copy_id, or None if it is not a run folder inside WORK_DIR."""
    if not isinstance(copy_id, str) or not COPY_ID.match(copy_id):
        return None
    work_dir = Path(config.WORK_DIR).resolve()
    folder = (work_dir / copy_id).resolve()
    if folder.parent != work_dir or not folder.is_dir():
        return None
    return folder


def read_meta(copy_id):
    folder = copy_folder(copy_id)
    if folder is None:
        return None, None
    return folder, json.loads((folder / META_FILE).read_text(encoding="utf-8"))


def remove_copy(copy_id):
    """Delete the run folder of copy_id. Refuses anything that is not a run folder inside WORK_DIR."""
    folder = copy_folder(copy_id)
    if folder is None:
        return False
    shutil.rmtree(folder)
    return True


def remove_stale_copies(max_age=None):
    """Remove run folders in WORK_DIR older than max_age seconds. Returns their names."""
    max_age = config.STALE_RUN_SECONDS if max_age is None else max_age
    work_dir = Path(config.WORK_DIR)
    if not work_dir.is_dir():
        return []
    cutoff = time.time() - max_age
    removed = []
    for path in sorted(work_dir.iterdir()):
        # copy_folder applies the same checks as the normal cleanup: name run-<id>, inside WORK_DIR.
        if copy_folder(path.name) is not None and path.stat().st_mtime < cutoff:
            remove_copy(path.name)
            removed.append(path.name)
    return removed
