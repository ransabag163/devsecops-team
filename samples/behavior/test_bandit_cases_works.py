"""Normal behavior of samples/bandit_cases.py. Must pass on the original and on a good fix.

There is no attack file for this sample: Bandit's rules have no attack tests.
read_config and fetch are not tested here, because yaml and requests are not installed.
"""

import builtins


def test_read_value_reads_a_python_value(sample, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt="": "[1, 2]")

    assert sample.read_value() == [1, 2]


def test_a_saved_session_loads_again(sample):
    session = {"user": "dana", "admin": False}

    assert sample.load_session(sample.save_session(session)) == session


def test_hash_password_is_stable_and_differs_per_password(sample):
    first = sample.hash_password("correct horse")

    assert isinstance(first, str) and first == sample.hash_password("correct horse")
    assert first != sample.hash_password("battery staple")
