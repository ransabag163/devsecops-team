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
