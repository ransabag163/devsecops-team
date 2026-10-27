"""The attack on samples/injection.py. Must FAIL on the original and PASS on a good fix."""

from behavior_helpers import command_words, uses_shell

PAYLOAD = "8.8.8.8; echo hacked"


def test_attack_shell_injection_host_is_not_run_by_a_shell(sample, commands):
    sample.ping(PAYLOAD)

    assert commands, "ping did not run any command"
    for call in commands:
        assert not uses_shell(call)
        assert PAYLOAD in command_words(call)  # one whole argument, not split into commands
