"""Merge the findings of the pen_tester's two tools: analyze_code and run_bandit.

The same line and the same CWE is ONE finding. It keeps the analyze_code rule
(which has an attack test) and lists every source with its own rule name.
"""

SOURCE_ORDER = ("analyze_code", "bandit")


def merge_findings(code_findings, bandit_findings):
    merged = []
    for finding in code_findings:
        merged.append({**finding, "sources": [{"tool": "analyze_code", "rule": finding["rule"]}]})
    for finding in bandit_findings:
        same = next((m for m in merged if m["line"] == finding["line"] and m["cwe"] == finding["cwe"]), None)
        source = {"tool": "bandit", "rule": finding["rule"]}
        if same is None:
            merged.append({**finding, "sources": [source]})
            continue
        same["sources"].append(source)
        if finding.get("message") and not same.get("message"):
            same["message"] = finding["message"]
    return sorted(merged, key=lambda f: (f["line"], f["rule"]))


def rule_names(finding):
    """Every name the model may use for this finding: its rule and each source's rule."""
    return {finding["rule"]} | {source["rule"] for source in finding.get("sources", [])}


def only_bandit(finding):
    """True if only Bandit found it. There is no attack test for it, so it can never be ready."""
    return all(source["tool"] == "bandit" for source in finding.get("sources", []))
