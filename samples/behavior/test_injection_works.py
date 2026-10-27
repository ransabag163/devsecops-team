"""Normal behavior of samples/injection.py. Must pass on the original and on a good fix."""

from behavior_helpers import command_words


def test_ping_runs_ping_on_the_host(sample, commands):
    sample.ping("example.com")

    assert len(commands) == 1
    words = command_words(commands[0])
    assert "ping" in words and "example.com" in words
