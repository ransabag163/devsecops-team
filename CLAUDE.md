# DevSecOps Agent Team - instructions for Claude

## The project
A course project for "AI Agents". Three Python agents work as a team:
- **pen_tester** - finds security weaknesses in Python code
- **developer** - proposes a small fix as a diff
- **tester** - runs tests to check that the fix closes the weakness and breaks nothing

A human approves every change to the original code. The team will later check the PRs of our final project.

## Environment
- Windows, Python 3.13, virtual environment in `.venv`.
- Run Python **only** as `.venv\Scripts\python.exe`. Bare `python` is blocked by the user's safety guard.
- Run tests: `.venv\Scripts\python.exe -m pytest -q`
- Install a package: `.venv\Scripts\python.exe -m pip install <name>`, then add it to `requirements.txt`.
- Work only inside this project folder. If the safety guard blocks something, stop and tell the user. Never try to get around it.

## Design rules
- One file per agent in `agents/`, tools in `tools/`, model adapters in `models/`.
- The model chooses, the application enforces: every tool call is checked against an allowlist before it runs, there is a `max_steps` limit, and every run ends with a status: `final`, `clarify`, `budget_exhausted` or `invalid_action`.
- Agents never modify the user's original file. They return a report or a diff.
- No secrets in code. API keys live only in `.env`, which is git-ignored.
- Keep the code simple and readable. This is a student project.
- Update `docs/ARCHITECTURE.md` (in Hebrew) in every step: diagrams, the file table, the enforced rules and the known limits must match the code on the branch.

## Git workflow
- Never commit to `main`. One branch per step, named `stepN-short-name`.
- Run the tests before every commit, and commit only if they pass.
- Small commits with clear English messages in the imperative ("Add pen tester rules").
- Push after every commit (`git push -u origin <branch>` the first time).
- Do not open or merge pull requests. The user opens the PR on GitHub and reviews it.
- Never force-push, never rewrite history, never delete files (no `git rm` / `git clean`). If something should be removed, ask the user.

## Talking to us
- Talk to us in **Hebrew**. Code, comments and commit messages in English.
- Before a change that touches more than a few files, say briefly what you plan to do.
- When you introduce a new concept, explain it in one or two simple sentences.
