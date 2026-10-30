"""The pen_tester agent: finds security weaknesses in one Python file.

It only reads the file and returns a FindingsReport. It never changes the file.

It must run both of its tools, analyze_code and run_bandit, on the file before
its final. Their findings are merged (the same line and CWE is one finding with
both sources), and the model gives a verdict for each merged finding. The agent
checks that verdict against what the tools really found: the model may not
drop, add or invent findings, and the cwe and evidence always come from the tools.
"""
import config
from pathlib import Path
from agents.base_agent import BaseAgent
from state import Finding, FindingsReport
from tools.findings import merge_findings, rule_names

VERDICTS = {"real", "false_positive"}
REQUIRED_TOOLS = ("analyze_code", "run_bandit")


class PenTester(BaseAgent):
    def __init__(self, model, max_steps=config.MAX_STEPS, project_root=config.PROJECT_ROOT):
        super().__init__("pen_tester", model, max_steps, project_root)

    def review(self, file_path):
        return self.run({"file_path": file_path, "actions": [], "observations": []})

    def check_final(self, action, state):
        report = action.get("report")
        if not isinstance(report, dict):
            return "final has no report"
        model_findings = report.get("findings", [])
        if not isinstance(model_findings, list):
            return "report findings is not a list"

        results = self._tool_results(state)
        missing_tools = [name for name in REQUIRED_TOOLS if name not in results]
        if missing_tools:
            return f"final before running both tools on the file (missing: {', '.join(missing_tools)})"
        if _first_error(results):
            return None if model_findings == [] else "findings reported although a tool failed"

        merged = _merged(results)
        names = {}  # every allowed (rule, line) -> the index of its merged finding
        for index, finding in enumerate(merged):
            for rule in rule_names(finding):
                names[(rule, finding["line"])] = index
        seen = set()
        for f in model_findings:
            if not isinstance(f, dict):
                return "a finding is not an object"
            key = _key(f)
            if key not in names:
                return f"final adds a finding the tools did not report: {key}"
            if names[key] in seen:
                return f"final repeats a finding: {key}"
            seen.add(names[key])
            if f.get("verdict") not in VERDICTS:
                return f"bad verdict for {key}: {f.get('verdict')!r}"
            if not isinstance(f.get("reason"), str) or not f["reason"].strip():
                return f"empty reason for {key}"
        missing = [_key(merged[i]) for i in range(len(merged)) if i not in seen]
        if missing:
            return f"final drops findings: {missing}"
        return None

    def finish(self, action, state):
        results = self._tool_results(state)
        error = _first_error(results)
        if error:
            return self.finish_with_error(error, state)

        merged = _merged(results)
        judged = {}
        for f in action["report"]["findings"]:
            judged[_key(f)] = f
        findings = []
        for i, f in enumerate(merged, start=1):
            verdict = next(judged[(rule, f["line"])] for rule in rule_names(f) if (rule, f["line"]) in judged)
            findings.append(Finding(
                id=f"F{i}",
                cwe=f["cwe"],
                rule=f["rule"],
                line=f["line"],
                evidence=f["evidence"],
                verdict=verdict["verdict"],
                reason=verdict["reason"].strip(),
                sources=f["sources"],
                message=f.get("message", ""),
            ))
        status = "findings" if findings else "no_findings"
        return FindingsReport(state["file_path"], status, findings).to_dict()

    def finish_with_error(self, error, state):
        return FindingsReport(state["file_path"], "input_error", [], error).to_dict()

    def _tool_results(self, state):
        """The latest result of each tool, counting only calls on the file under review."""
        results = {}
        target = self._resolve(state.get("file_path"))
        for action, observation in zip(state.get("actions", []), state.get("observations", [])):
            args = action.get("args")
            if not isinstance(args, dict) or target is None or self._resolve(args.get("file_path")) != target:
                continue
            if action.get("name") in REQUIRED_TOOLS:
                results[action["name"]] = observation
        return results

    def _resolve(self, file_path):
        if not isinstance(file_path, str):
            return None
        return (Path(self.project_root) / file_path).resolve()


def _first_error(results):
    """The error of the first tool that failed, as "tool: error", or None."""
    for name in REQUIRED_TOOLS:
        if not results[name].get("ok"):
            return results[name].get("error") if name == "analyze_code" else f"{name}: {results[name].get('error')}"
    return None


def _merged(results):
    return merge_findings(results["analyze_code"]["findings"], results["run_bandit"]["findings"])


def _key(finding):
    """A finding is named by a rule and a line."""
    return (finding.get("rule"), finding.get("line"))
