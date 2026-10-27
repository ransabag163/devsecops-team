"""One time limit for a whole main.py run (config.RUN_DEADLINE_SECONDS).

Every agent checks it before each step, and the model client checks it before
each request and each retry. hit becomes True when something was stopped or
skipped because of it, so main.py can report it and exit with 2.
"""

import time


def now():
    """The clock. Tests replace it so they never really wait."""
    return time.monotonic()


class Deadline:
    def __init__(self, seconds):
        self.seconds = seconds
        self.end = now() + seconds
        self.hit = False

    def remaining(self):
        return max(0.0, self.end - now())

    def passed(self):
        return self.remaining() <= 0
