"""The decision component of an agent.

A model looks at the current state and returns ONE action (a dict):
  {"kind": "tool", "name": "<tool>", "args": {...}}   ask to run a tool
  {"kind": "final", "text": "...", "report": {...}}   the work is done
  {"kind": "clarify", "text": "..."}                  a question for the human

The model only chooses. The agent loop and the registry enforce the rules.
"""

ACTION_KINDS = ("tool", "final", "clarify")


class DecisionModel:
    def decide(self, state):
        raise NotImplementedError

    def last_retries(self):
        """Retries of the last decide() call, for the trace. Only LLM models retry."""
        return []

    def last_extra_objects(self):
        """JSON objects after the first one in the last reply, ignored. Only LLM models write replies."""
        return 0

    def set_deadline(self, deadline):
        """Give the model the run's Deadline. Only LLM models need it (for their requests)."""

    def request_count(self):
        """Real model API requests made so far. Only LLM models make any."""
        return 0
