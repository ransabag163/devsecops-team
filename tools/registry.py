"""The only way an agent can run a tool.

The model only *asks* for a tool. execute() decides if the request is allowed
and runs it. Every check happens here, before the tool runs.
"""

from pathlib import Path

from tools.analyze_code import analyze_code
from tools.patch_tools import make_diff, read_snippet
from tools.verify_tools import rescan, run_behavior_tests

# Every tool, with the exact arguments it accepts and their types.
TOOLS = {
    "analyze_code": {"func": analyze_code, "args": {"file_path": str}},
    "read_snippet": {
        "func": read_snippet,
        "args": {"file_path": str, "start_line": int, "end_line": int},
    },
    "make_diff": {
        "func": make_diff,
        "args": {"file_path": str, "start_line": int, "end_line": int, "replacement": str},
    },
    # copy_id names a run folder in WORK_DIR; the tools refuse anything else.
    "rescan": {"func": rescan, "args": {"copy_id": str}},
    "run_behavior_tests": {"func": run_behavior_tests, "args": {"copy_id": str}},
}

# Which tools each agent may use.
ALLOWLIST = {
    "pen_tester": {"analyze_code"},
    "developer": {"read_snippet", "make_diff"},
    "tester": {"rescan", "run_behavior_tests"},
}

# Arguments that hold a file path and must stay inside the project.
PATH_ARGS = {"file_path"}


def execute(agent_name, action, project_root):
    name = action.get("name")
    args = action.get("args")

    if name not in TOOLS:
        return {"ok": False, "error": "unknown_tool"}
    if name not in ALLOWLIST.get(agent_name, set()):
        return {"ok": False, "error": "tool_not_allowed"}

    expected = TOOLS[name]["args"]
    if not isinstance(args, dict) or set(args) != set(expected):
        return {"ok": False, "error": "invalid_arguments"}
    for arg_name, arg_type in expected.items():
        if type(args[arg_name]) is not arg_type:
            return {"ok": False, "error": "invalid_arguments"}

    root = Path(project_root).resolve()
    call_args = dict(args)
    for arg_name in PATH_ARGS & set(args):
        path = (root / args[arg_name]).resolve()
        if not path.is_relative_to(root):
            return {"ok": False, "error": "path_outside_project"}
        call_args[arg_name] = str(path)

    return TOOLS[name]["func"](**call_args)
