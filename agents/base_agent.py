"""The agent loop: the model chooses, the application enforces.

Every run ends with one status:
  final            the model finished the work
  clarify          the model needs an answer from the human
  invalid_action   the model returned something that is not a known action
  budget_exhausted the model used all max_steps without finishing
"""

import config
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

        state = {**state, "observations": list(state.get("observations", []))}
        trace = []

        for step in range(1, self.max_steps + 1):
            action = self.model.decide(state)
            entry = {"step": step, "action": action}
            trace.append(entry)

            kind = action.get("kind") if isinstance(action, dict) else None
            if kind == "final":
                return {"status": "final", "result": self.finish(action, state), "trace": trace}
            if kind == "clarify":
                return {"status": "clarify", "result": action.get("text"), "trace": trace}
            if kind != "tool":
                return {"status": "invalid_action", "result": None, "trace": trace}

            # Tools run only through the registry, which checks the allowlist.
            observation = execute(self.name, action, self.project_root)
            entry["observation"] = observation
            state["observations"].append(observation)

        return {"status": "budget_exhausted", "result": None, "trace": trace}

    def finish(self, action, state):
        """Turn the final action into the agent's result. Subclasses override this."""
        return action.get("text")
