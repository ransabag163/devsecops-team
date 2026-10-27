import pytest

from state import Finding, FindingsReport, FixReport, PatchProposal, Verification, VerificationReport


def test_report_to_dict_includes_findings():
    finding = Finding("F1", "CWE-89", "sql_concat", 3, "cur.execute(q)", "real", "rule match")
    report = FindingsReport("app.py", "findings", [finding])

    data = report.to_dict()

    assert data["status"] == "findings"
    assert data["findings"][0]["id"] == "F1"
    assert data["error"] is None


def test_unknown_status_is_rejected():
    with pytest.raises(ValueError):
        FindingsReport("app.py", "maybe")


def test_fix_report_to_dict_includes_proposals():
    proposal = PatchProposal("F1", "proposed", 5, 5, "x = 1", "--- a\n+++ b\n", "use env")
    report = FixReport("app.py", "fixes", [proposal])

    data = report.to_dict()

    assert data["proposals"][0]["finding_id"] == "F1"
    assert data["proposals"][0]["diff"].startswith("--- a")


@pytest.mark.parametrize("make", [
    lambda: PatchProposal("F1", "maybe"),
    lambda: FixReport("app.py", "done"),
])
def test_unknown_fix_statuses_are_rejected(make):
    with pytest.raises(ValueError):
        make()


def test_verification_report_to_dict():
    verification = Verification("F1", True, [], "passed", "passed", "approve", "", "final")
    report = VerificationReport("app.py", "verified", [verification])

    data = report.to_dict()

    assert data["verifications"][0] == {
        "finding_id": "F1", "closed": True, "new_findings": [], "works": "passed",
        "attack": "passed", "verdict": "approve", "feedback": "", "status": "final",
    }


@pytest.mark.parametrize("make", [
    lambda: Verification("F1", True, [], "passed", "passed", "ship it", "", "final"),
    lambda: VerificationReport("app.py", "done"),
])
def test_unknown_verdicts_and_statuses_are_rejected(make):
    with pytest.raises(ValueError):
        make()
