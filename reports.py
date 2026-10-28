"""Decision cards for main.py review: one card per real finding, for a human.

The report is written twice: reports/<file>-<timestamp>.json (read by apply)
and .md (read by a person). Cards that need a human come first, then the
ready ones. The report keeps the sha256 of the original file, so apply can
refuse if the file changed since the review.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import config
from tools.findings import only_bandit

# One plain line per rule, for the person who reads the card.
PROBLEMS = {
    "hardcoded_secret": "סיסמה או מפתח כתובים בתוך הקוד, וכל מי שרואה את הקוד רואה אותם.",
    "sql_concat": "קלט של משתמש מודבק לתוך שאילתת SQL, ולכן קלט מתוחכם יכול לשנות את השאילתה.",
    "shell_injection": "קלט של משתמש מגיע לפקודת shell, ולכן קלט מתוחכם יכול להריץ פקודות אחרות.",
}
STATUS_ORDER = {"needs_you": 0, "ready": 1}
FULL_PROOF = "attack test"
PARTIAL_PROOF = "partial proof: no attack test"
PARTIAL_NOTE = ("הוכחה חלקית: רק Bandit מצא את הממצא הזה, ואין לו טסט התקפה. הבדיקות מראות רק ש־Bandit"
                " כבר לא מדווח עליו ושהקוד עדיין עובד, לא שההתקפה נחסמה. לכן הכרטיס תמיד צריך אותך.")


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_card(file_path, finding, status, attack_before, attempts, notes=()):
    """Build one card. attempts is the finding's history, oldest first:
    [{"number", "proposal" or None, "verification" or None, "feedback"}]. The last one decides."""
    last = attempts[-1] if attempts else {}
    proposal = last.get("proposal") or {}
    verification = last.get("verification") or {}
    failed = attempts[:-1] if status == "ready" else attempts
    checks = {
        "closed": verification.get("closed"),
        "new_findings": verification.get("new_findings"),
        "works": verification.get("works", "not_run"),
        "attack": verification.get("attack", "not_run"),
    }
    change = None
    if proposal.get("status") == "proposed":
        change = {key: proposal[key] for key in ("start_line", "end_line", "replacement")}
    partial = only_bandit(finding)
    if partial:
        notes = [PARTIAL_NOTE, *notes]
    return {
        "id": finding["id"],
        "status": status,
        "cwe": finding["cwe"],
        "rule": finding["rule"],
        "file": file_path,
        "line": finding["line"],
        "sources": finding.get("sources", []),
        "proof": PARTIAL_PROOF if partial else FULL_PROOF,
        "problem": PROBLEMS.get(finding["rule"]) or finding.get("message") or "חולשה שהכלי מצא. קרא את הנימוק.",
        "reason": finding.get("reason", ""),
        "attack": {"before": attack_before, "after": checks["attack"]},
        "change": change,
        "diff": proposal.get("diff"),
        "checks": checks,
        "attempts": len(attempts),
        "failed_attempts": [{"number": a["number"], "feedback": a["feedback"]} for a in failed],
        "look_here": _look_here(status, attack_before, checks, verification, notes, partial),
    }


def _look_here(status, attack_before, checks, verification, notes, partial=False):
    """What a human should check: the tester's note, and what the application could not verify."""
    items = list(notes)
    if verification.get("verdict") == "human" and verification.get("feedback"):
        items.append(f"הערת ה־tester לאדם: {verification['feedback']}")
    if attack_before != "failed" and not partial:  # partial: the note above already says there is no attack test
        items.append(f"טסט ההתקפה לא נכשל על הקובץ המקורי ({attack_before}), ולכן הוא לא מוכיח שהחולשה קיימת.")
    if status == "needs_you":
        for kind in ("works",) if partial else ("works", "attack"):
            if checks[kind] not in ("passed", "not_run"):  # not_run: no proposal reached the tests
                items.append(f"טסטי {kind}: {checks[kind]}.")
    return items


def build_report(file_path, sha256, cards, not_done, stop_reason, status, model_requests):
    ordered = sorted(cards, key=lambda card: (STATUS_ORDER[card["status"]], card["id"]))
    return {
        "file": file_path,
        "sha256": sha256,
        "created": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "cards": ordered,
        "not_done": list(not_done),
        "stop_reason": stop_reason,
        "model_requests": model_requests,
    }


def write_report(report):
    """Write the .json and .md files. Returns their paths relative to the project."""
    folder = Path(config.REPORTS_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{Path(report['file']).stem}-{datetime.now():%Y%m%d-%H%M%S}"
    stem, number = base, 1
    while (folder / f"{stem}.json").exists():  # two reviews in the same second
        number += 1
        stem = f"{base}_{number}"
    json_path, md_path = folder / f"{stem}.json", folder / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(report, _relative(json_path)), encoding="utf-8")
    return {"json": _relative(json_path), "md": _relative(md_path)}


def _relative(path):
    try:
        return path.resolve().relative_to(Path(config.PROJECT_ROOT).resolve()).as_posix()
    except ValueError:
        return str(path)


RESULT_TEXT = {"failed": "נכשל", "passed": "עבר", "not_run": "לא רץ", "not_available": "אין טסט"}


def render_markdown(report, json_path="<report .json>"):
    lines = [
        f"# דוח בדיקה: `{report['file']}`",
        "",
        f"- נוצר: {report['created']}",
        f"- sha256 של הקובץ המקורי: `{report['sha256']}`",
        f"- מצב: {report['status']}",
    ]
    if report["stop_reason"]:
        lines.append(f"- הריצה נעצרה: {report['stop_reason']}")
    for status, title in (("needs_you", "צריך אותך"), ("ready", "מוכן להחלה")):
        cards = [c for c in report["cards"] if c["status"] == status]
        lines += ["", f"## {title} ({len(cards)})"]
        for card in cards:
            lines += [""] + _render_card(card)
    if report["not_done"]:
        lines += ["", "## לא נעשה", ""] + [f"- {item}" for item in report["not_done"]]
    ready = [c["id"] for c in report["cards"] if c["status"] == "ready"]
    if ready:
        lines += ["", "## להחלה", "", "רק אחרי שקראת את הכרטיסים:", "",
                  "```", f"main.py apply {json_path} --ids {','.join(ready)}", "```"]
    return "\n".join(lines) + "\n"


def _render_card(card):
    checks = card["checks"]
    new = checks["new_findings"]
    lines = [
        f"### {card['id']} · {card['cwe']} · {card['rule']}",
        "",
        f"- **מיקום:** `{card['file']}`, שורה {card['line']}",
        "- **נמצא על ידי:** " + (", ".join(f"{s['tool']} ({s['rule']})" for s in card["sources"]) or "-"),
        f"- **הוכחה:** {card['proof']}",
        f"- **הבעיה:** {card['problem']}",
        f"- **נימוק ה־pen_tester:** {card['reason']}",
        f"- **טסט ההתקפה** (נכשל = ההתקפה הצליחה, עבר = ההתקפה נחסמה): "
        f"לפני – {RESULT_TEXT.get(card['attack']['before'], card['attack']['before'])}"
        f" · אחרי – {RESULT_TEXT.get(card['attack']['after'], card['attack']['after'])}",
        f"- **בדיקות:** closed: {checks['closed']} · ממצאים חדשים: {len(new) if new is not None else 'לא נבדק'}"
        f" · works: {checks['works']} · attack: {checks['attack']}",
        f"- **ניסיונות:** {card['attempts']}",
    ]
    for attempt in card["failed_attempts"]:
        lines.append(f"  - ניסיון {attempt['number']} נכשל: {attempt['feedback']}")
    if card["look_here"]:
        lines.append("- **שים לב:**")
        lines += [f"  - {item}" for item in card["look_here"]]
    if card["diff"]:
        lines += ["", "```diff", card["diff"].rstrip("\n"), "```"]
    return lines
