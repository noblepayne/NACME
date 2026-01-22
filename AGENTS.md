# AGENTS.md

This file contains instructions for any AI agents (Grok, Gemini, Claude, OpenCode, Cursor, etc.) that assist with the NACME project.  
The goal is consistent, high-quality contributions aligned with project structure and philosophy.

## Core Rules

1. **Project Structure Awareness**  
   - `ARCHITECTURE.md` and `DEVLOG.md` live in `docs/`  
   - `CHANGELOG.md`, `README.md`, `flake.nix`, source files (`nacme_server.py`, `nacme_client.py`, etc.) live in project root  
   - Tests go in `tests/` (create folder when first needed)  
   - Always update the correct file in the correct location.

2. **Mandatory Actions on Every Meaningful Change**
   - **Write or update tests** (pytest) for any new code, refactored logic, or bug fix.  
     - Use `pytest-asyncio` for async code.  
     - Mock external dependencies (plumbum/nebula-cert, DB) where possible.  
     - Aim for good coverage of happy path + key errors.  
   - **Append to docs/DEVLOG.md** after every session or significant task.  
     - Format: `### YYYY-MM-DD – Short Title` followed by bullet-point summary, decisions, gotchas, next steps, signed off with your name/handle and time zone.  
   - **Update CHANGELOG.md** (in root) under `## Unreleased` for any user-visible or structural change.  
     - Use conventional sections: Added, Changed, Fixed, Removed.  
   - **Update README.md** (in root) for any user-facing change (new env var, usage example, installation note, etc.).  
   - **Update docs/ARCHITECTURE.md** only when there is a meaningful design shift (rare).

3. **Code Style & Quality**
   - Follow PEP 8 + type hints everywhere possible.
   - **Import Style**: Clojure-style namespaced imports only. No `from x import y` except in tests or tightly coupled APIs. Always maintain at least one level of namespacing. No `import *` allowed.
     - Good: `import os.path`, `import collections.abc`, `import urllib.parse`
     - Bad: `from os import path`, `from collections import abc`
     - Exceptions: Tests, or when a library's API is super coupled (rare, case-by-case)
   - Prefer plain SQL + aiosqlite (no ORM, no query builders).
   - Keep server single-file for now; refactor to modules only when it becomes painful (>800–1000 LOC).
   - Use structured logging (`structlog`) in server code.
   - Handle errors explicitly (log + raise appropriate HTTPException).
   - Prefer env vars + pydantic for all configuration.

4. **Testing Expectations**
   - Every PR/commit that touches logic must have accompanying tests.
   - **Preference**: End-to-end, blackbox, and integration tests over unit tests.
   - Use **Hypothesis** for generative/property-based testing to validate invariants.
   - Use **icontract** for design-by-contract contracts and pre/postconditions.
   - Use fixtures for DB (in-memory SQLite preferred for speed).
   - Mock `plumbum` calls to `nebula-cert` (monkeypatch or fake process).
   - Run `pytest -v` locally and confirm green before suggesting changes.

5. **Documentation Discipline**
   - README.md: user-focused (how to run, env vars, examples).
   - docs/ARCHITECTURE.md: stable design overview (update only for big shifts).
   - docs/DEVLOG.md: honest, chronological journal (gotchas, why decisions were made).
   - CHANGELOG.md: release-oriented, semantic versioning friendly.

6. **Workflow Reminders**
   - After generating code/docs: self-review checklist  
     - Does it pass tests?  
     - Updated DEVLOG.md?  
     - Updated CHANGELOG.md if user-visible?  
     - README updated if needed?  
     - Files in correct locations?  
   - If adding a new feature, propose tests + docs changes in the same response.
   - Prefer small, focused changes over large refactors unless explicitly asked.

7. **Agent-Specific Notes**
   - Grok: feel free to use X search / real-time tools when researching Nebula ecosystem or similar projects.
   - All agents: if unsure about prior decisions, check DEVLOG.md first.

When you complete a task, end your response with:

```
Task complete.  
Updated: [list files changed, e.g. nacme_server.py, docs/DEVLOG.md]  
Ready for next task.
```

If something is unclear, ask clarifying questions before proceeding.
