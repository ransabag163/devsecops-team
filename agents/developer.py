"""The developer agent: proposes a small fix for each real finding.

It never changes the file. Each proposal is a separate diff against the
original file, and the human decides what to apply.

The model proposes lines to replace. The application checks the proposal and
makes the diff itself with make_diff, so a diff written by the model is never used.
"""

import config
from agents.base_agent import BaseAgent
from state import FixReport, PatchProposal
from tools.registry import execute

MAX_DISTANCE = 10  # the change must touch or be this close to the finding line


class Developer(BaseAgent):
    def __init__(self, model, max_steps=config.DEVELOPER_MAX_STEPS, project_root=config.PROJECT_ROOT):
        super().__init__("developer", model, max_steps, project_root)

    def fix(self, findings_report):
        """Run the loop once per real finding. false_positive findings are never sent."""
        file_path = findings_report["file"]
        real = [f for f in findings_report["findings"] if f["verdict"] == "real"]
        proposals, problems, runs, not_done = [], [], [], []

        for index, finding in enumerate(real):
            if self.out_of_time():
                not_done = [f["id"] for f in real[index:]]
                problems.append("not done (run deadline): " + ", ".join(not_done))
                break
            run = self.fix_one(file_path, finding)
            runs.append({"finding_id": finding["id"], "status": run["status"], "trace": run["trace"]})

            if run["status"] != "final":
                problems.append(f"{finding['id']}: {run['status']} ({run['result']})")
                continue
            if "error" in run["result"]:  # the model itself could not be reached
                report = FixReport(file_path, "input_error", proposals, run["result"]["error"])
                return {"status": "final", "result": report.to_dict(), "runs": runs, "not_done": not_done}
            proposals.append(PatchProposal(**run["result"]))

        status = "fixes" if any(p.status == "proposed" for p in proposals) else "no_fixes"
        report = FixReport(file_path, status, proposals, "; ".join(problems) or None)
        # "final" only when every finding's run ended in final; else the first failure.
        overall = next((r["status"] for r in runs if r["status"] != "final"), "final")
        if not_done:
            overall = "budget_exhausted"
        return {"status": overall, "result": report.to_dict(), "runs": runs, "not_done": not_done}

    def fix_one(self, file_path, finding, feedback=None, previous=()):
        """One attempt to fix one finding. Returns the run (status, result, trace).

        feedback is the note on the last failed attempt; the model gets it as DATA.
        previous holds the earlier proposals for this finding.
        """
        state = {"file_path": file_path, "finding": finding, "actions": [], "observations": [],
                 "previous_proposals": [dict(p) for p in previous]}
        if feedback:
            state["feedback"] = feedback
        return self.run(state)

    def check_final(self, action, state):
        proposal = action.get("proposal")
        if not isinstance(proposal, dict):
            return "final has no proposal"
        expected_id = state["finding"]["id"]
        if proposal.get("finding_id") != expected_id:
            return f"proposal is for {proposal.get('finding_id')!r}, expected {expected_id!r}"
        explanation = proposal.get("explanation")
        if not isinstance(explanation, str):
            return "explanation must be a string"

        status = proposal.get("status")
        if status == "skipped":
            return None if explanation.strip() else "skipped needs an explanation"
        if status != "proposed":
            return f"bad proposal status: {status!r}"

        start, end, replacement = proposal.get("start_line"), proposal.get("end_line"), proposal.get("replacement")
        if type(start) is not int or type(end) is not int or not isinstance(replacement, str):
            return "proposed needs int start_line, int end_line and str replacement"
        line = state["finding"]["line"]
        distance = 0 if start <= line <= end else min(abs(start - line), abs(end - line))
        if distance > MAX_DISTANCE:
            return f"change is {distance} lines from the finding on line {line}"
        for number, earlier in enumerate(state.get("previous_proposals", []), 1):
            if (start, end, replacement) == (earlier.get("start_line"), earlier.get("end_line"), earlier.get("replacement")):
                return f"the same change as attempt {number}, which already failed"

        # Never trust a diff from the model: make it again with the real tool.
        result = execute("developer", {"kind": "tool", "name": "make_diff", "args": {
            "file_path": state["file_path"], "start_line": start, "end_line": end, "replacement": replacement,
        }}, self.project_root)
        if not result.get("ok"):
            return f"make_diff failed: {result.get('error')}"
        state["checked_diff"] = result["diff"]
        return None

    def finish(self, action, state):
        proposal = action["proposal"]
        if proposal["status"] == "skipped":
            return PatchProposal(state["finding"]["id"], "skipped", explanation=proposal["explanation"].strip()).to_dict()
        return PatchProposal(
            finding_id=state["finding"]["id"],
            status="proposed",
            start_line=proposal["start_line"],
            end_line=proposal["end_line"],
            replacement=proposal["replacement"],
            diff=state["checked_diff"],
            explanation=proposal["explanation"].strip(),
        ).to_dict()

    def finish_with_error(self, error, state):
        return {"error": error}
