"""The pen_tester agent: finds security weaknesses in one Python file.

It only reads the file and returns a FindingsReport. It never changes the file.
"""

import config
from agents.base_agent import BaseAgent
from state import Finding, FindingsReport


class PenTester(BaseAgent):
    def __init__(self, model, max_steps=config.MAX_STEPS, project_root=config.PROJECT_ROOT):
        super().__init__("pen_tester", model, max_steps, project_root)

    def review(self, file_path):
        return self.run({"file_path": file_path, "observations": []})

    def finish(self, action, state):
        report = action.get("report") or {}
        error = report.get("error")
        findings = [
            Finding(
                id=f"F{i}",
                cwe=f["cwe"],
                rule=f["rule"],
                line=f["line"],
                evidence=f["evidence"],
                verdict=f["verdict"],
                reason=f["reason"],
            )
            for i, f in enumerate(report.get("findings", []), start=1)
        ]

        if error:
            status = "input_error"
        elif findings:
            status = "findings"
        else:
            status = "no_findings"
        return FindingsReport(state["file_path"], status, findings, error).to_dict()
