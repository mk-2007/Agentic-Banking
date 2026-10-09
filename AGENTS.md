# AGENTS.md - operating manual for AI agents

Read this first. It tells you how to get oriented and how to work without breaking the project.

## 1. Get oriented (in this order)
1. `README.md` - what the project is and the current phase status.
2. `docs/context/graph.json` - modules, phases, decisions and their relationships.
3. `docs/architecture.md` and `docs/adr/` - the rules and why they exist.
4. `docs/PROJECT_LOG.md` - what changed recently.
5. `docs/source/` - the original PRD and knowledge base (the spec).

## 2. Non-negotiable rules
- **Authorization is plain code, never an LLM.** Do not put permission logic in prompts.
- **Agents never import `bank_sim`.** They reach the bank only through `tools`. Layer rules are tested.
- **Recommend vs authorize.** Decision output is a recommendation; execution needs an approved ID.
- **Synthetic data only.** Never add real personal or financial data, secrets, or keys. Use `.env` (git-ignored).
- **Closed action set.** The decision layer chooses from a fixed enum, never free text.
- Do not claim a model output is a calibrated probability unless it has been calibrated on our scenarios.

## 3. How to work
- One phase at a time, in the order in the README. Do not start a later phase early.
- Small, typed, documented code. Every package keeps its docstring (what, why, where it sits).
- Write tests with the code; safety-critical parts (security, audit, approvals) get tests first.
- Commands (from `backend/`): `pytest -q`, `ruff check .`, `ruff format .`, `mypy`.
- Commit style: conventional commits, e.g. `feat(tools): add permission check`.

## 4. Keeping project memory current (required after every change)
Before you finish, update whichever apply:
- `README.md` status table when a phase changes state.
- `docs/context/graph.json`: set node `status` (`planned` / `in_progress` / `done`), add new
  modules/decisions as nodes and their relationships as edges. New package => new `module:` node.
- `docs/PROJECT_LOG.md`: add a dated entry for what you did and decided.
- `docs/adr/`: a new ADR for any decision that changes an architectural rule.
Then run `pytest -q`; `tests/architecture/` fails if the graph or layer rules drift.

## 5. Graph format
Nodes: `id` (`module:x`, `phase:n`, `adr:nnnn`, `doc:x`, `concept:x`), `type`, `status`, optional
`path` (must exist) and `summary`. Edges: `from`, `to`, `relation` in
`depends_on | implements | documents | decides | constrains`.

## 6. Known open items
- JEV (TypeSafe AI) is not available to us. If access appears, add a provider adapter behind
  `decision/` (see ADR 0002); do not restructure other layers.
- Fraud thresholds and the approval matrix are not in the knowledge base; they will be written as a
  synthetic policy document in phase 2.
