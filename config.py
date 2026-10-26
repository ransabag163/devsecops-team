"""Project-wide settings."""

from pathlib import Path

# The folder that contains this file. Tools may only touch files inside it.
PROJECT_ROOT = Path(__file__).resolve().parent

# How many decisions an agent may make before we stop it.
MAX_STEPS = 4

# Files larger than this are not analyzed.
MAX_FILE_BYTES = 200_000
