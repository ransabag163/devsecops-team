"""Read-only static analysis of one Python file, based on the ast module.

Rules:
- CWE-89  sql_concat:        SQL text built with +, %, f-string or .format
                             and passed to .execute() (directly or via a variable)
- CWE-798 hardcoded_secret:  a non-empty string literal assigned to a name
                             like password / secret / api_key / token
- CWE-78  shell_injection:   subprocess call with shell=True and a non-literal
                             command, or os.system with a non-literal argument
"""

import ast
import re
from pathlib import Path

import config

SQL_WORDS = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
SECRET_NAMES = re.compile(r"password|passwd|secret|api_key|token", re.IGNORECASE)
SUBPROCESS_FUNCS = {"run", "call", "Popen", "check_call", "check_output"}
MAX_EVIDENCE = 120
CONTEXT_LINES = 5
MAX_CONTEXT = 1500


def analyze_code(file_path):
    path = Path(file_path)
    if not path.is_file():
        return {"ok": False, "error": "file_not_found"}
    if path.suffix.lower() != ".py":
        return {"ok": False, "error": "unsupported_language"}
    if path.stat().st_size > config.MAX_FILE_BYTES:
        return {"ok": False, "error": "file_too_large"}

    data = path.read_bytes()
    try:
        tree = ast.parse(data, filename=str(path))
    except (SyntaxError, ValueError):
        return {"ok": False, "error": "syntax_error"}

    lines = data.decode("utf-8", errors="replace").splitlines()
    found = []
    found += _find_sql_concat(tree)
    found += _find_hardcoded_secrets(tree)
    found += _find_shell_injection(tree)

    findings = []
    seen = set()
    for rule, cwe, line in sorted(found, key=lambda f: (f[2], f[0])):
        if (rule, line) in seen:
            continue
        seen.add((rule, line))
        findings.append({
            "rule": rule,
            "cwe": cwe,
            "line": line,
            "evidence": _evidence(lines, line),
            "context": _context(lines, line),
        })
    return {"ok": True, "findings": findings}


def _evidence(lines, line):
    if 1 <= line <= len(lines):
        return lines[line - 1].strip()[:MAX_EVIDENCE]
    return ""


def _context(lines, line):
    """The source lines around a finding, with line numbers, so a model can judge it."""
    start = max(1, line - CONTEXT_LINES)
    end = min(len(lines), line + CONTEXT_LINES)
    text = "\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1))
    return text[:MAX_CONTEXT]


# ---------- CWE-89: SQL built from pieces and passed to execute() ----------

def _find_sql_concat(tree):
    found = []
    for scope in _scopes(tree):
        built_names = set()
        for node in _walk_scope(scope):
            if isinstance(node, ast.Assign) and _is_built_sql(node.value):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        built_names.add(target.id)
        for node in _walk_scope(scope):
            if _is_execute_call(node) and node.args:
                query = node.args[0]
                via_variable = isinstance(query, ast.Name) and query.id in built_names
                if via_variable or _is_built_sql(query):
                    found.append(("sql_concat", "CWE-89", node.lineno))
    return found


def _is_execute_call(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    )


def _is_built_sql(node):
    """True when node builds a SQL string from a literal plus non-literal parts."""
    if isinstance(node, ast.JoinedStr):  # f-string
        has_value = any(isinstance(v, ast.FormattedValue) for v in node.values)
        return has_value and _has_sql_text(node)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return _has_sql_text(node) and not _is_literal(node)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
        and (node.args or node.keywords)
    ):
        return _has_sql_text(node.func.value)
    return False


def _has_sql_text(node):
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if SQL_WORDS.search(child.value):
                return True
    return False


# ---------- CWE-798: secret written as a string literal ----------

def _find_hardcoded_secrets(tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value):
            continue
        for target in targets:
            name = _target_name(target)
            if name and SECRET_NAMES.search(name):
                found.append(("hardcoded_secret", "CWE-798", node.lineno))
    return found


def _target_name(target):
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):  # self.password = "..."
        return target.attr
    return None


# ---------- CWE-78: shell command built from non-literal input ----------

def _find_shell_injection(tree):
    imported = _names_imported_from(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        module, func = _call_target(node, imported)
        if module == "subprocess" and func in SUBPROCESS_FUNCS:
            command = _first_arg(node, "args")
            if _has_shell_true(node) and command is not None and not _is_literal(command):
                found.append(("shell_injection", "CWE-78", node.lineno))
        elif module == "os" and func == "system":
            command = _first_arg(node, "command")
            if command is not None and not _is_literal(command):
                found.append(("shell_injection", "CWE-78", node.lineno))
    return found


def _names_imported_from(tree):
    """Map names like `run` (from `from subprocess import run`) to their module."""
    imported = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("subprocess", "os"):
            for alias in node.names:
                imported[alias.asname or alias.name] = (node.module, alias.name)
    return imported


def _call_target(call, imported):
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id, func.attr
    if isinstance(func, ast.Name) and func.id in imported:
        return imported[func.id]
    return None, None


def _first_arg(call, keyword_name):
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == keyword_name:
            return kw.value
    return None


def _has_shell_true(call):
    return any(
        kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in call.keywords
    )


# ---------- helpers ----------

def _is_literal(node):
    """True when node is made only of constant strings (or lists/tuples of them)."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return all(_is_literal(e) for e in node.elts)
    if isinstance(node, ast.BinOp):
        return _is_literal(node.left) and _is_literal(node.right)
    return False


def _scopes(tree):
    """The module itself plus every function, each analyzed on its own."""
    yield tree
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _walk_scope(scope):
    """Like ast.walk, but does not enter nested functions or classes."""
    todo = list(ast.iter_child_nodes(scope))
    while todo:
        node = todo.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            todo.extend(ast.iter_child_nodes(node))
