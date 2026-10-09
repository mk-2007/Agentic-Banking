# Contributing

This project moves in phases (see the README status table). Work is tracked with GitHub issues and
milestones, and every change lands through a pull request.

## Workflow
1. Pick an issue from the current milestone (or open one with the Feature template).
2. Branch from `main`: `feat/<short-name>`, `fix/<short-name>`, `docs/<short-name>` or `chore/<short-name>`.
3. Make small commits using conventional commit messages, for example `feat(tools): add permission check`.
4. Run the checks from `backend/`: `pytest -q`, `ruff check .`, `ruff format --check .`, `mypy`.
5. Open a pull request. Fill in the template and write `Closes #<issue>` so the issue closes on merge.
6. Merge when CI is green.

## Ground rules
- Read `AGENTS.md` and `docs/architecture.md` first. The layer rules are enforced by tests.
- Authorization is plain code, never an LLM. Agents reach the bank only through tools.
- Synthetic data only. Never commit secrets (`.env` is git-ignored).
- When project state changes, update the README status, `docs/context/graph.json` and `docs/PROJECT_LOG.md`.

## Commit types
`feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`.
