"""Read-only tools for the developer agent. They never write any file.

- read_snippet: show numbered source lines
- make_diff:    replace lines in an in-memory copy and return a unified diff
"""

import ast
import difflib
from pathlib import Path

import config

MAX_SNIPPET_LINES = 60
MAX_ORIGINAL_LINES = 15
MAX_REPLACEMENT_LINES = 30


def read_snippet(file_path, start_line, end_line):
    loaded = _load(file_path)
    if not loaded["ok"]:
        return loaded
    lines = loaded["lines"]

    if start_line < 1 or start_line > len(lines) or end_line < start_line:
        return {"ok": False, "error": "invalid_range"}
    end_line = min(end_line, len(lines), start_line + MAX_SNIPPET_LINES - 1)

    snippet = "\n".join(
        f"{n}: {lines[n - 1].rstrip(chr(13) + chr(10))}" for n in range(start_line, end_line + 1)
    )
    return {"ok": True, "start_line": start_line, "end_line": end_line, "snippet": snippet}


def make_diff(file_path, start_line, end_line, replacement):
    change = apply_change(file_path, start_line, end_line, replacement)
    if not change["ok"]:
        return change

    name = _display_name(file_path)
    diff = "\n".join(difflib.unified_diff(
        _strip(change["lines"]), _strip(change["patched"]), fromfile=f"a/{name}", tofile=f"b/{name}", lineterm="",
    ))
    return {"ok": True, "start_line": start_line, "end_line": end_line, "diff": diff + "\n"}


def apply_change(file_path, start_line, end_line, replacement):
    """Check a change and apply it to an in-memory copy of the file.

    Returns {"ok": True, "lines": original lines, "patched": new lines} or an error.
    make_diff and the tester's patched copies both use it, so they apply the same rules.
    """
    return apply_changes(file_path, [(start_line, end_line, replacement)])


def apply_changes(file_path, changes):
    """Apply several (start_line, end_line, replacement) changes to one in-memory copy.

    Each change is checked like make_diff, the changes may not overlap, and the
    whole patched file must still parse. Used by apply for the combined copy.
    """
    loaded = _load(file_path)
    if not loaded["ok"]:
        return loaded
    lines = loaded["lines"]
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"

    ordered = sorted(changes, key=lambda change: change[0])
    for index, (start_line, end_line, replacement) in enumerate(ordered):
        if start_line < 1 or end_line < start_line or end_line > len(lines):
            return {"ok": False, "error": "invalid_range"}
        new_lines = replacement.splitlines()
        if end_line - start_line + 1 > MAX_ORIGINAL_LINES or len(new_lines) > MAX_REPLACEMENT_LINES:
            return {"ok": False, "error": "change_too_large"}
        if _strip(lines[start_line - 1:end_line]) == new_lines:
            return {"ok": False, "error": "empty_change"}
        if index > 0 and start_line <= ordered[index - 1][1]:
            return {"ok": False, "error": "overlapping_changes"}

    patched = list(lines)
    for start_line, end_line, replacement in reversed(ordered):  # bottom first, so line numbers stay valid
        patched[start_line - 1:end_line] = [line + newline for line in replacement.splitlines()]
    try:
        ast.parse("".join(patched))
    except (SyntaxError, ValueError):
        return {"ok": False, "error": "syntax_error"}
    return {"ok": True, "lines": lines, "patched": patched}


def _load(file_path):
    path = Path(file_path)
    if not path.is_file():
        return {"ok": False, "error": "file_not_found"}
    if path.suffix.lower() != ".py":
        return {"ok": False, "error": "unsupported_language"}
    if path.stat().st_size > config.MAX_FILE_BYTES:
        return {"ok": False, "error": "file_too_large"}
    text = path.read_bytes().decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    if not lines:
        return {"ok": False, "error": "invalid_range"}
    return {"ok": True, "lines": lines}


def _strip(lines):
    return [line.rstrip("\r\n") for line in lines]


def _display_name(file_path):
    path = Path(file_path).resolve()
    if path.is_relative_to(config.PROJECT_ROOT):
        return path.relative_to(config.PROJECT_ROOT).as_posix()
    return path.name
