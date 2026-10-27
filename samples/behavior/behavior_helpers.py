"""Helpers for the behavior tests: how to read a recorded command."""

SHELL_VIAS = ("os.system", "os.popen", "subprocess.getoutput", "subprocess.getstatusoutput")
# os.exec*/os.spawn* start a program directly, never through a shell.
DIRECT_VIAS = ("os.exec", "os.spawn")


def _command(call):
    return call["args"][0] if call["args"] else call["kwargs"].get("args")


def uses_shell(call):
    """True if this call would hand its command to a shell."""
    if call["via"] in SHELL_VIAS or call["kwargs"].get("shell"):
        return True
    if call["via"].startswith(DIRECT_VIAS):
        return False
    return isinstance(_command(call), str)


def command_words(call):
    """The words of the command, whether it was given as one string or as a list."""
    if call["via"].startswith(DIRECT_VIAS):
        # The argument list (execv/spawnv), or the arguments one by one (execl).
        lists = [item for item in call["args"] if isinstance(item, (list, tuple))]
        if lists:
            return [str(word) for word in lists[0]]
        return [item for item in call["args"] if isinstance(item, str)]
    command = _command(call)
    if isinstance(command, str):
        return command.split()
    return [str(word) for word in command]
