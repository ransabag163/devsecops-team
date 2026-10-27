import pytest

from state import Finding, FindingsReport, FixReport, PatchProposal


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
