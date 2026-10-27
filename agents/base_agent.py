"""The agent loop: the model chooses, the application enforces.

Every run ends with one status:
  final            the model finished the work
  clarify          the model needs an answer from the human
  invalid_action   the model returned something that is not a valid action
  budget_exhausted the model used all max_steps, or the run deadline passed, without finishing
"""

import config
from models.llm_adapter import LLMError
from tools.registry import execute

DEADLINE_RESULT = "run deadline passed"


class BaseAgent:
    def __init__(self, name, model, max_steps=config.MAX_STEPS, project_root=config.PROJECT_ROOT):
        self.name = name
        self.model = model
        self.max_steps = max_steps
        self.project_root = project_root
        # The run's Deadline (see deadline.py), set by main.py. None means no time limit.
        self.deadline = None
        # Called with (agent name, finding id, trace entry) as soon as each step is complete.
        # main.py uses it to print the trace live with --trace.
        self.on_step = None

    def run(self, state):
        if type(self.max_steps) is not int or self.max_steps < 1:
            raise ValueError("max_steps must be a positive int")

        state = {
            **state,
            "actions": list(state.get("actions", [])),
            "observations": list(state.get("observations", [])),
        }
        trace = []
        if self.deadline is not None:
            self.model.set_deadline(self.deadline)

        for step in range(1, self.max_steps + 1):
            if self.out_of_time():
                trace.append({"step": step, "action": None, "error": "run_deadline"})
                return self._end("budget_exhausted", DEADLINE_RESULT, trace, state)
            try:
                action = self.model.decide(state)
            except LLMError as e:
                # The model could not be reached. Only the error code (and HTTP status) is kept.
                entry = {"step": step, "action": None, "error": str(e)}
                self.add_retries(entry)
                trace.append(entry)
                if self.out_of_time():
                    return self._end("budget_exhausted", DEADLINE_RESULT, trace, state)
                return self._end("final", self.finish_with_error(str(e), state), trace, state)

            entry = {"step": step, "action": action}
            self.add_retries(entry)
            trace.append(entry)

            kind = action.get("kind") if isinstance(action, dict) else None
            if kind == "final":
                problem = self.check_final(action, state)
                if problem:
                    return self._end("invalid_action", problem, trace, state)
                return self._end("final", self.finish(action, state), trace, state)
            if kind == "clarify":
                return self._end("clarify", action.get("text"), trace, state)
            if kind != "tool":
                return self._end("invalid_action", f"unknown action kind: {kind!r}", trace, state)

            # Tools run only through the registry, which checks the allowlist.
            observation = execute(self.name, action, self.project_root)
            entry["observation"] = observation
            self.emit(entry, state)
            state["actions"].append(action)
            state["observations"].append(observation)

        return {"status": "budget_exhausted", "result": None, "trace": trace}

    def _end(self, status, result, trace, state):
        self.emit(trace[-1], state)
        return {"status": status, "result": result, "trace": trace}

    def emit(self, entry, state):
        if self.on_step is not None:
            self.on_step(self.name, state.get("finding", {}).get("id"), entry)

    def out_of_time(self):
        """True if the run deadline passed. Marks the deadline as hit, so main.py reports it."""
        if self.deadline is None or not self.deadline.passed():
            return False
        self.deadline.hit = True
        return True

    def add_retries(self, entry):
        """Record the model call's retries (attempt and status only), if there were any."""
        retries = self.model.last_retries()
        if retries:
            entry["retries"] = retries

    def check_final(self, action, state):
        """Return a short problem description if the final action breaks a rule, else None.
        Subclasses override this."""
        return None

    def finish(self, action, state):
        """Turn the final action into the agent's result. Subclasses override this."""
        return action.get("text")

    def finish_with_error(self, error, state):
        """The result when the model itself failed. Subclasses override this."""
        return error
