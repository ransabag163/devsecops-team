import pytest

from state import Finding, FindingsReport


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
