import json

import pytest

import config
import deadline as deadline_module
from agents.base_agent import BaseAgent
from deadline import Deadline
from main import main
from models.base import DecisionModel
from models.llm_adapter import LLMClient, LLMError
from models.scripted import ScriptedDeveloperModel


@pytest.fixture
def clock(monkeypatch):
    """A fake clock for deadline.py: tests move it by hand, nothing really waits."""
    now = [1000.0]
    monkeypatch.setattr(deadline_module, "now", lambda: now[0])
    return now


def test_deadline_counts_down(clock):
    d = Deadline(10)

    clock[0] += 4
    assert (d.remaining(), d.passed()) == (6, False)
    clock[0] += 6
    assert (d.remaining(), d.passed()) == (0, True)


# ---------- the agent loop ----------

class SlowModel(DecisionModel):
    """Asks for a tool and moves the clock forward each time."""

    def __init__(self, clock, seconds):
        self.clock, self.seconds = clock, seconds

    def decide(self, state):
        self.clock[0] += self.seconds
        return {"kind": "tool", "name": "analyze_code", "args": {"file_path": "samples/clean.py"}}


def test_agent_stops_when_the_deadline_passes(clock):
    agent = BaseAgent("pen_tester", SlowModel(clock, 6), max_steps=4)
    agent.deadline = Deadline(10)

    run = agent.run({})

    assert run["status"] == "budget_exhausted"
    assert run["result"] == "run deadline passed"
    assert [e["step"] for e in run["trace"]] == [1, 2, 3]  # step 3 never asked the model
    assert run["trace"][-1] == {"step": 3, "action": None, "error": "run_deadline"}
    assert agent.deadline.hit is True


def test_a_model_error_after_the_deadline_is_budget_exhausted(clock):
    class TimesOut(DecisionModel):
        def decide(self, state):
            clock[0] += 100
            raise LLMError("timeout")

    agent = BaseAgent("pen_tester", TimesOut())
    agent.deadline = Deadline(10)

    assert agent.run({})["status"] == "budget_exhausted"


# ---------- the model client ----------

class Transport:
    def __init__(self, status=200):
        self.status, self.timeouts = status, []

    def __call__(self, url, headers, body, timeout):
        self.timeouts.append(timeout)
        return self.status, json.dumps({"choices": [{"message": {"content": "hi"}}]}), None


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-tests-123")


def test_client_never_waits_past_the_deadline(clock, key):
    transport = Transport()
    client = LLMClient("groq", transport, timeout=30)
    client.deadline = Deadline(12)

    client.chat([])

    assert transport.timeouts == [12]


def test_client_does_not_start_a_request_after_the_deadline(clock, key):
    transport = Transport()
    client = LLMClient("groq", transport)
    client.deadline = Deadline(5)
    clock[0] += 5

    with pytest.raises(LLMError) as error:
        client.chat([])

    assert error.value.code == "run_deadline"
    assert transport.timeouts == []


def test_client_does_not_retry_without_time_left(clock, key):
    transport = Transport(status=503)
    client = LLMClient("groq", transport, sleep=lambda s: None)
    client.deadline = Deadline(1.5)  # less than the first retry wait (2s)

    with pytest.raises(LLMError) as error:
        client.chat([])

    assert str(error.value) == "http_error (503)"
    assert len(transport.timeouts) == 1


# ---------- main.py ----------

def test_main_reports_what_was_not_done_and_exits_with_2(capsys, monkeypatch, clock):
    monkeypatch.setattr(config, "RUN_DEADLINE_SECONDS", 0)

    code = main(["samples/login.py", "--verify"])
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["findings_report"]["status"] == "budget_exhausted"
    assert output["run_deadline"] == {"seconds": 0, "not_done": ["developer: all findings", "tester: all proposals"]}


def test_deadline_during_the_developer_skips_the_other_findings(capsys, monkeypatch, clock):
    original = ScriptedDeveloperModel.decide

    def slow_decide(self, state):
        clock[0] += 1000  # the first developer step uses up the whole run
        return original(self, state)

    monkeypatch.setattr(ScriptedDeveloperModel, "decide", slow_decide)

    code = main(["samples/login.py", "--verify"])
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["run_deadline"]["not_done"] == ["developer: F2", "developer: F3"]
    assert "not done (run deadline): F2, F3" in output["fix_report"]["error"]
