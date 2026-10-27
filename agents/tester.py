"""The tester agent: checks each proposed fix on a patched copy.

The application applies the proposal to a copy in WORK_DIR, the model runs the
checks and chooses a verdict (approve, retry or human). The application
decides what the checks said, from the tool results only, and allows "approve"
only when every check passed. The model can make a verdict stricter, never looser.
"""

import config
from agents.base_agent import BaseAgent
from state import VERDICTS, Verification, VerificationReport
from tools.verify_tools import collect_checks, failed_checks
from tools.workspace import create_copy, remove_copy


class Tester(BaseAgent):
    __test__ = False  # the name starts with "Test", so tell pytest this is not a test class

    def __init__(self, model, max_steps=config.TESTER_MAX_STEPS, project_root=config.PROJECT_ROOT):
        super().__init__("tester", model, max_steps, project_root)

    def verify(self, findings_report, fix_report, keep_work=False):
        """Run the loop once per proposed fix. Skipped proposals have nothing to check."""
        file_path = fix_report["file"]
        findings = {f["id"]: f for f in findings_report["findings"]}
        verifications, runs, not_done = [], [], []
        proposed = [p for p in fix_report["proposals"] if p["status"] == "proposed"]

        for index, proposal in enumerate(proposed):
            if self.out_of_time():
                not_done = [p["finding_id"] for p in proposed[index:]]
                break
            finding_id = proposal["finding_id"]
            checked = self.verify_one(file_path, findings[finding_id], proposal, keep_work)
            if checked["run"] is not None:
                runs.append(checked["run"])
            if "error" in checked:  # the model itself could not be reached
                report = VerificationReport(file_path, "input_error", verifications, checked["error"])
                return {"status": "final", "result": report.to_dict(), "runs": runs, "not_done": not_done}
            verifications.append(checked["verification"])

        error = "not done (run deadline): " + ", ".join(not_done) if not_done else None
        report = VerificationReport(file_path, "verified" if verifications else "no_proposals", verifications, error)
        # "final" only when every proposal's run ended in final; else the first failure.
        overall = next((r["status"] for r in runs if r["status"] != "final"), "final")
        if not_done:
            overall = "budget_exhausted"
        return {"status": overall, "result": report.to_dict(), "runs": runs, "not_done": not_done}

    def verify_one(self, file_path, finding, proposal, keep_work=False):
        """Check one proposal on a fresh patched copy, then remove the copy.

        Returns {"status", "verification": Verification, "run"}, or {"status", "error", "run"}
        when the model could not be reached. run is None if no copy could be made.
        """
        finding_id = finding["id"]
        copy = create_copy(file_path, finding, proposal)
        if not copy["ok"]:
            verification = Verification(finding_id, None, None, "not_run", "not_run", "human",
                                        f"The application could not apply the proposal: {copy['error']}", "final")
            return {"status": "final", "verification": verification, "run": None}

        copy_id = copy["copy_id"]
        try:
            run = self.run({"file_path": file_path, "finding": finding, "proposal": proposal,
                            "copy_id": copy_id, "actions": [], "observations": []})
        finally:
            if not keep_work:
                remove_copy(copy_id)
        run_info = {"finding_id": finding_id, "status": run["status"], "copy_id": copy_id, "trace": run["trace"]}
        if run["status"] == "final" and "error" in run["result"]:
            return {"status": "final", "error": run["result"]["error"], "run": run_info}
        return {"status": run["status"], "verification": _verification(finding_id, run, copy_id), "run": run_info}

    def check_final(self, action, state):
        verification = action.get("verification")
        if not isinstance(verification, dict):
            return "final has no verification"
        expected_id = state["finding"]["id"]
        if verification.get("finding_id") != expected_id:
            return f"verification is for {verification.get('finding_id')!r}, expected {expected_id!r}"
        verdict, feedback = verification.get("verdict"), verification.get("feedback")
        if verdict not in VERDICTS:
            return f"bad verdict: {verdict!r}"
        if not isinstance(feedback, str):
            return "feedback must be a string"
        if verdict == "retry" and not feedback.strip():
            return "retry needs feedback for the developer"
        if verdict == "approve":
            problems = failed_checks(collect_checks(state["actions"], state["observations"], state["copy_id"]))
            if problems:
                return "approve is not allowed: " + "; ".join(problems)
        return None

    def finish(self, action, state):
        verification = action["verification"]
        return {"verdict": verification["verdict"], "feedback": verification["feedback"].strip()}

    def finish_with_error(self, error, state):
        return {"error": error}


def _verification(finding_id, run, copy_id):
    """Build the result from the tool results in the trace and the verdict of the run."""
    tool_entries = [entry for entry in run["trace"] if "observation" in entry]
    checks = collect_checks([e["action"] for e in tool_entries], [e["observation"] for e in tool_entries], copy_id)
    if run["status"] == "final":
        verdict, feedback = run["result"]["verdict"], run["result"]["feedback"]
    else:
        # The run did not end cleanly (for example a blocked approve): a human must look.
        verdict, feedback = "human", f"tester run ended in {run['status']}: {run['result']}"
    return Verification(finding_id, checks["closed"], checks["new_findings"], checks["works"], checks["attack"],
                        verdict, feedback, run["status"])
