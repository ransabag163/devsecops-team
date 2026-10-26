"""A rule-based model: fixed if/else decisions, no AI and no API.

It trusts every rule match. Judging the context of a finding is what the
real model adds in step 2.
"""

from models.base import DecisionModel


class ScriptedPenTesterModel(DecisionModel):
    def decide(self, state):
        file_path = state.get("file_path")
        observations = state.get("observations", [])

        if not file_path:
            return {"kind": "clarify", "text": "Which Python file should I check?"}

        if not observations:
            return {"kind": "tool", "name": "analyze_code", "args": {"file_path": file_path}}

        last = observations[-1]
        if not last.get("ok"):
            return {
                "kind": "final",
                "text": f"Could not analyze the file: {last.get('error')}",
                "report": {"findings": [], "error": last.get("error")},
            }

        findings = [
            {**f, "verdict": "real", "reason": "rule match"}
            for f in last["findings"]
        ]
        return {
            "kind": "final",
            "text": f"Found {len(findings)} finding(s).",
            "report": {"findings": findings, "error": None},
        }
