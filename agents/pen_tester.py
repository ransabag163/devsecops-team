"""The pen_tester agent: finds security weaknesses in one Python file.

It only reads the file and returns a FindingsReport. It never changes the file.

The model gives a verdict for each finding. The agent checks that verdict
against what the tool really found: the model may not drop, add or invent
findings, and the cwe and evidence always come from the tool.
"""

import config
from agents.base_agent import BaseAgent
from state import Finding, FindingsReport

VERDICTS = {"real", "false_positive"}


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

        tool_result = _last_tool_result(state)
        if tool_result is None:
            return "final before the file was analyzed"
        if not tool_result.get("ok"):
            return None if model_findings == [] else "findings reported although the tool failed"

        expected = {_key(f) for f in tool_result["findings"]}
        seen = set()
        for f in model_findings:
            if not isinstance(f, dict):
                return "a finding is not an object"
            key = _key(f)
            if key not in expected:
                return f"final adds a finding the tool did not report: {key}"
            if key in seen:
                return f"final repeats a finding: {key}"
            seen.add(key)
            if f.get("verdict") not in VERDICTS:
                return f"bad verdict for {key}: {f.get('verdict')!r}"
            if not isinstance(f.get("reason"), str) or not f["reason"].strip():
                return f"empty reason for {key}"
        missing = expected - seen
        if missing:
            return f"final drops findings: {sorted(missing)}"
        return None

    def finish(self, action, state):
        tool_result = _last_tool_result(state)
        if not tool_result.get("ok"):
            return self.finish_with_error(tool_result.get("error"), state)

        judged = {_key(f): f for f in action["report"]["findings"]}
        findings = []
        for i, f in enumerate(tool_result["findings"], start=1):
            verdict = judged[_key(f)]
            findings.append(Finding(
                id=f"F{i}",
                cwe=f["cwe"],
                rule=f["rule"],
                line=f["line"],
                evidence=f["evidence"],
                verdict=verdict["verdict"],
                reason=verdict["reason"].strip(),
            ))
        status = "findings" if findings else "no_findings"
        return FindingsReport(state["file_path"], status, findings).to_dict()

    def finish_with_error(self, error, state):
        return FindingsReport(state["file_path"], "input_error", [], error).to_dict()


def _last_tool_result(state):
    observations = state.get("observations", [])
    return observations[-1] if observations else None


def _key(finding):
    """A finding is identified by its rule and line."""
    return (finding.get("rule"), finding.get("line"))
