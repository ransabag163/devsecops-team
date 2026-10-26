"""The agent loop: the model chooses, the application enforces.

Every run ends with one status:
  final            the model finished the work
  clarify          the model needs an answer from the human
  invalid_action   the model returned something that is not a valid action
  budget_exhausted the model used all max_steps without finishing
"""

import config
from models.llm_adapter import LLMError
from tools.registry import execute


class BaseAgent:
    def __init__(self, name, model, max_steps=config.MAX_STEPS, project_root=config.PROJECT_ROOT):
        self.name = name
        self.model = model
        self.max_steps = max_steps
        self.project_root = project_root

    def run(self, state):
        if type(self.max_steps) is not int or self.max_steps < 1:
            raise ValueError("max_steps must be a positive int")

        state = {
            **state,
            "actions": list(state.get("actions", [])),
            "observations": list(state.get("observations", [])),
        }
        trace = []

        for step in range(1, self.max_steps + 1):
            try:
                action = self.model.decide(state)
            except LLMError as e:
                # The model could not be reached. Only the error code is kept.
                trace.append({"step": step, "action": None, "error": e.code})
                return {"status": "final", "result": self.finish_with_error(e.code, state), "trace": trace}

            entry = {"step": step, "action": action}
            trace.append(entry)

            kind = action.get("kind") if isinstance(action, dict) else None
            if kind == "final":
                problem = self.check_final(action, state)
                if problem:
                    return {"status": "invalid_action", "result": problem, "trace": trace}
                return {"status": "final", "result": self.finish(action, state), "trace": trace}
            if kind == "clarify":
                return {"status": "clarify", "result": action.get("text"), "trace": trace}
            if kind != "tool":
                return {"status": "invalid_action", "result": f"unknown action kind: {kind!r}", "trace": trace}

            # Tools run only through the registry, which checks the allowlist.
            observation = execute(self.name, action, self.project_root)
            entry["observation"] = observation
            state["actions"].append(action)
            state["observations"].append(observation)

        return {"status": "budget_exhausted", "result": None, "trace": trace}

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
