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
from tools.patch_tools import apply_change

COPY_ID = re.compile(r"^run-[0-9a-f]{8}$")
META_FILE = "meta.json"


def create_copy(file_path, finding, proposal):
    """Apply a proposal to a copy of file_path. Returns {"ok": True, "copy_id": ...} or an error."""
    source = (config.PROJECT_ROOT / file_path).resolve()
    if not source.is_relative_to(config.PROJECT_ROOT):
        return {"ok": False, "error": "path_outside_project"}
    start, end, replacement = proposal["start_line"], proposal["end_line"], proposal["replacement"]
    change = apply_change(source, start, end, replacement)
    if not change["ok"]:
        return change

    copy_id = f"run-{uuid.uuid4().hex[:8]}"
    folder = Path(config.WORK_DIR) / copy_id
    folder.mkdir(parents=True)
    (folder / source.name).write_text("".join(change["patched"]), encoding="utf-8", newline="")
    meta = {
        "file": source.relative_to(config.PROJECT_ROOT).as_posix(),
        "copy_file": source.name,
        "sample": source.stem,
        "rule": finding["rule"],
        "finding_line": finding["line"],
        "start_line": start,
        "end_line": end,
        # The last line of the change in the copy (start - 1 if the change only deletes lines).
        "new_end_line": start + len(replacement.splitlines()) - 1,
    }
    (folder / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"ok": True, "copy_id": copy_id}


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
