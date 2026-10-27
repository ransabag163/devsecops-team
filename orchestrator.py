"""The team run (main.py review) as a LangGraph graph. Only this file imports LangGraph.

LangGraph in four words:
- State: one dict that the whole run shares (ReviewState). Every node reads it
  and returns only the keys it changes.
- Node:  one step of the run, a plain function (scan, next_finding, develop,
  verify, report). Each node calls at most one agent.
- Edge:  "after this node, go to that node" (START -> scan, report -> END).
- Conditional edge: a small function that looks at the state and returns the
  name of the next node, for example retry -> develop, approve -> next_finding.

The agents do not know about the graph. The graph only decides the order;
every rule is still enforced by the agents and the application.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import reports
from tools.verify_tools import run_behavior_tests
from tools.workspace import create_original_copy, remove_copy, resolve_in_project

MAX_ATTEMPTS = 3
# LangGraph stops a graph after this many node runs; 3 findings x 3 attempts need about 25.
RECURSION_LIMIT = 100
DEADLINE_REASON = "run deadline passed"


class ReviewState(TypedDict, total=False):
    file_path: str
    sha256: str | None
    findings_report: dict | None
    queue: list            # real findings not started yet
    finding: dict | None   # the finding being worked on
    attack_before: str     # its attack test on an unchanged copy of the original
    attempts: list         # its attempts: {"number", "proposal", "verification", "feedback"}
    proposal: dict | None  # the latest proposal, waiting for verify
    outcome: str           # what develop or verify decided; read by the conditional edges
    cards: list
    not_done: list
    stop_reason: str | None
    runs: dict             # the traces of every agent run, for --trace
    final_report: dict


class Orchestrator:
    def __init__(self, pen_tester, developer, tester, deadline, keep_work=False, on_event=None):
        self.pen_tester, self.developer, self.tester = pen_tester, developer, tester
        self.deadline = deadline
        self.keep_work = keep_work
        # Called with a small dict each time a node starts (main.py prints it with --trace).
        self.on_event = on_event
        self.graph = self.build_graph()

    def build_graph(self):
        graph = StateGraph(ReviewState)
        graph.add_node("scan", self.scan)
        graph.add_node("next_finding", self.next_finding)
        graph.add_node("develop", self.develop)
        graph.add_node("verify", self.verify)
        graph.add_node("report", self.report)

        # Each conditional edge returns a label; the dict maps the label to the next node.
        # The labels also appear on the arrows of the drawn graph.
        graph.add_edge(START, "scan")
        graph.add_conditional_edges("scan", self.after_scan, {
            "real findings": "next_finding", "none or error": "report"})
        graph.add_conditional_edges("next_finding", self.after_next_finding, {
            "a finding": "develop", "none left or deadline": "report"})
        graph.add_conditional_edges("develop", self.after_develop, {
            "proposed": "verify", "rejected, try again": "develop",
            "skipped or 3 attempts: needs_you": "next_finding", "stop": "report"})
        graph.add_conditional_edges("verify", self.after_verify, {
            "retry, under 3 attempts": "develop", "approve: ready, or needs_you": "next_finding", "stop": "report"})
        graph.add_edge("report", END)
        return graph.compile()

    def review(self, file_path):
        """Run the whole graph on one file. Returns the final state; the report is in final_report."""
        start = {"file_path": file_path, "queue": [], "finding": None, "attempts": [], "proposal": None,
                 "cards": [], "not_done": [], "stop_reason": None,
                 "runs": {"pen_tester": None, "developer": [], "tester": []}}
        return self.graph.invoke(start, {"recursion_limit": RECURSION_LIMIT})

    # ---------- nodes ----------

    def scan(self, state):
        self.emit("scan")
        source = resolve_in_project(state["file_path"]) if state["file_path"] else None
        sha256 = reports.file_sha256(source) if source is not None and source.is_file() else None
        run = self.pen_tester.review(state["file_path"])
        runs = {**state["runs"], "pen_tester": run["trace"]}
        if run["status"] != "final" or run["result"]["status"] == "input_error":
            if self.out_of_time():
                reason = DEADLINE_REASON
            elif run["status"] == "final":
                reason = f"pen_tester: {run['result']['error']}"
            else:
                reason = f"pen_tester: {run['status']} ({run['result']})"
            return {"runs": runs, "sha256": sha256, "findings_report": None, "stop_reason": reason,
                    "not_done": ["all findings"]}
        real = [f for f in run["result"]["findings"] if f["verdict"] == "real"]
        return {"runs": runs, "sha256": sha256, "findings_report": run["result"], "queue": real}

    def next_finding(self, state):
        if self.out_of_time():
            return {"stop_reason": DEADLINE_REASON, "finding": None}
        if not state["queue"]:
            return {"finding": None}
        finding, rest = state["queue"][0], state["queue"][1:]
        self.emit("next_finding", finding["id"])
        return {"finding": finding, "queue": rest, "attempts": [], "proposal": None,
                "attack_before": self.attack_before(state["file_path"], finding)}

    def develop(self, state):
        finding, attempts = state["finding"], state["attempts"]
        number = len(attempts) + 1
        if self.out_of_time():
            return {"stop_reason": DEADLINE_REASON, "outcome": "stop"}
        self.emit("develop", finding["id"], number)

        feedback = attempts[-1]["feedback"] if attempts else None
        previous = [a["proposal"] for a in attempts if a["proposal"] and a["proposal"]["status"] == "proposed"]
        run = self.developer.fix_one(state["file_path"], finding, feedback, previous)
        runs = self._add_run(state, "developer", finding["id"], number, run["status"], run["trace"])

        if run["status"] == "final" and "error" in run["result"]:  # the model could not be reached
            return {"runs": runs, "stop_reason": f"developer: {run['result']['error']}", "outcome": "stop"}
        if run["status"] == "final":
            proposal = run["result"]
            if proposal["status"] == "proposed":
                return {"runs": runs, "proposal": proposal, "outcome": "verify"}
            attempt = {"number": number, "proposal": proposal, "verification": None,
                       "feedback": f"the developer skipped it: {proposal['explanation']}"}
            card = self.card(state, "needs_you", attempts + [attempt],
                             [f"ה־developer לא הציע תיקון: {proposal['explanation']}"])
            return {"runs": runs, "attempts": attempts + [attempt], "cards": state["cards"] + [card],
                    "outcome": "done"}

        if self.out_of_time():
            return {"runs": runs, "stop_reason": DEADLINE_REASON, "outcome": "stop"}
        # The application rejected the attempt (for example the same change again): a failed attempt.
        attempt = {"number": number, "proposal": None, "verification": None,
                   "feedback": f"the application rejected the attempt ({run['status']}): {run['result']}"}
        return self.after_failed_attempt(state, runs, attempt)

    def verify(self, state):
        finding, attempts, proposal = state["finding"], state["attempts"], state["proposal"]
        number = len(attempts) + 1
        if self.out_of_time():
            return {"stop_reason": DEADLINE_REASON, "outcome": "stop"}
        self.emit("verify", finding["id"], number)

        checked = self.tester.verify_one(state["file_path"], finding, proposal, self.keep_work)
        runs = state["runs"]
        if checked["run"] is not None:
            run = checked["run"]
            runs = self._add_run(state, "tester", finding["id"], number, run["status"], run["trace"], run["copy_id"])
        if "error" in checked:  # the model could not be reached
            return {"runs": runs, "stop_reason": f"tester: {checked['error']}", "outcome": "stop"}
        if checked["status"] == "budget_exhausted" and self.out_of_time():
            return {"runs": runs, "stop_reason": DEADLINE_REASON, "outcome": "stop"}

        verification = checked["verification"].to_dict()
        attempt = {"number": number, "proposal": proposal, "verification": verification,
                   "feedback": verification["feedback"]}
        if verification["verdict"] == "approve":
            card = self.card(state, "ready", attempts + [attempt])
            return {"runs": runs, "attempts": attempts + [attempt], "cards": state["cards"] + [card],
                    "outcome": "done"}
        if verification["verdict"] == "retry":
            return self.after_failed_attempt(state, runs, attempt)
        card = self.card(state, "needs_you", attempts + [attempt])  # human
        return {"runs": runs, "attempts": attempts + [attempt], "cards": state["cards"] + [card], "outcome": "done"}

    def report(self, state):
        self.emit("report")
        not_done = list(state["not_done"])
        finding = state.get("finding")
        if finding and finding["id"] not in {card["id"] for card in state["cards"]}:
            not_done.append(finding["id"])  # stopped in the middle of this finding
        not_done += [f["id"] for f in state.get("queue", [])]

        if state["findings_report"] is None:
            status = "error"
        elif state["stop_reason"] or not_done:
            status = "partial"
        elif not state["cards"]:
            status = "no_findings"
        else:
            status = "complete"
        requests = {name: agent.model.request_count()
                    for name, agent in (("pen_tester", self.pen_tester), ("developer", self.developer),
                                        ("tester", self.tester))}
        final_report = reports.build_report(state["file_path"], state.get("sha256"), state["cards"], not_done,
                                            state["stop_reason"], status, requests)
        return {"final_report": final_report, "not_done": not_done}

    # ---------- conditional edges: they only choose the next node ----------

    def after_scan(self, state):
        return "none or error" if state["stop_reason"] or not state["queue"] else "real findings"

    def after_next_finding(self, state):
        return "none left or deadline" if state["stop_reason"] or state["finding"] is None else "a finding"

    def after_develop(self, state):
        return {"verify": "proposed", "develop": "rejected, try again",
                "done": "skipped or 3 attempts: needs_you", "stop": "stop"}[state["outcome"]]

    def after_verify(self, state):
        return {"develop": "retry, under 3 attempts", "done": "approve: ready, or needs_you",
                "stop": "stop"}[state["outcome"]]

    # ---------- helpers ----------

    def after_failed_attempt(self, state, runs, attempt):
        """Try again with the feedback, or give the finding to a human after MAX_ATTEMPTS."""
        attempts = state["attempts"] + [attempt]
        if len(attempts) < MAX_ATTEMPTS:
            return {"runs": runs, "attempts": attempts, "proposal": None, "outcome": "develop"}
        card = self.card(state, "needs_you", attempts, [f"{MAX_ATTEMPTS} ניסיונות נכשלו."])
        return {"runs": runs, "attempts": attempts, "cards": state["cards"] + [card], "outcome": "done"}

    def card(self, state, status, attempts, notes=()):
        return reports.make_card(state["file_path"], state["finding"], status, state["attack_before"], attempts, notes)

    def attack_before(self, file_path, finding):
        """Run the finding's attack test once on an unchanged copy. Expected: failed."""
        copy = create_original_copy(file_path, finding)
        if not copy["ok"]:
            return "not_run"
        try:
            result = run_behavior_tests(copy["copy_id"])
        finally:
            if not self.keep_work:
                remove_copy(copy["copy_id"])
        return result["attack"] if result.get("ok") else "not_run"

    def out_of_time(self):
        if self.deadline is None or not self.deadline.passed():
            return False
        self.deadline.hit = True
        return True

    def emit(self, node, finding_id=None, attempt=None):
        if self.on_event is not None:
            self.on_event({"graph": node, "finding_id": finding_id, "attempt": attempt})

    def _add_run(self, state, agent, finding_id, attempt, status, trace, copy_id=None):
        run = {"finding_id": finding_id, "attempt": attempt, "status": status, "trace": trace}
        if copy_id:
            run["copy_id"] = copy_id
        return {**state["runs"], agent: state["runs"][agent] + [run]}


def draw_mermaid(orchestrator):
    """The graph as Mermaid text, drawn by LangGraph itself (for docs/ARCHITECTURE.md)."""
    return orchestrator.graph.get_graph().draw_mermaid()
