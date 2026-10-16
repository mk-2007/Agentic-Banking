# Resume here

A short, current snapshot so any new session (human or AI) can continue without re-reading everything.
**Update it at the end of every work session**, in the same PR as the work. Keep it under 80 lines.
Starting a new AI chat? Give it this file, `AGENTS.md`, and the latest repo zip
(`git archive -o repo.zip HEAD`).

## Where we are
- Phases 0-5 done (domain, bank sim, tools, RAG, model gateway, specialist agents). **Phase 6a done**
  (LangGraph case graph, `docs/orchestration.md`). **6b done** (approval pause and resume via `decide=` and
  `resume_case`). **Next: 6c** (limits, retries, audit per transition), then 6d. See `docs/TRACKER.md` for the split.
- 523 tests pass; `ruff`, `mypy` clean. `python scripts/run_agent_eval.py` passes 7 of 7 scenarios and
  `python scripts/run_case.py --all` reaches `decision_ready` on all seven.

## What to read first
1. `AGENTS.md` (rules every contributor and agent follows)
2. `docs/context/graph.json` (machine-readable map of modules, ADRs, docs)
3. `docs/agents.md` and `docs/architecture.md` (how the pieces fit)
4. `docs/PROJECT_LOG.md` (what changed and why, newest first)

## Commands (PowerShell, repo root)
```
python -m pip install -e "backend[dev]"
cd backend; python -m ruff check .; python -m ruff format --check .; python -m mypy; python -m pytest -q; cd ..
python scripts/run_agent_eval.py            # offline, no keys
python scripts/run_agent_eval.py --live     # real model in the policy step
python scripts/llm_smoke_test.py            # provider check (keys in .env)
```

## Rules that must not erode
- Layering is enforced by `tests/architecture/`; agents never touch the bank, only tools.
- Case status changes only in `orchestration/nodes.py`; state holds contracts and lists; checkpoint types are allowlisted.
- Agents exchange typed findings (`IndicatorCode`), never prose; third-party text never reaches evidence or prompts.
- Model output is validated before use; a failed model never blocks an investigation.
- Actions are risk-levelled; Level 4 needs two human approvers; orchestration code (never a model) builds approvals.
- Synthetic data only. No keys or real personal data in the repo.

## Known gaps (also in docs/agents.md and docs/llm-gateway.md)
- Gemini has never completed a live call (503 overloaded when tried). Groq works.
- The policy agent's model step is tested with a scripted provider only.
- `instruction_text` detection is a heuristic; conflict detection is coarse (over-escalates).

## Decisions to remember
ADR 0001-0009 in `docs/adr/`. Latest: 0008 (typed findings, deterministic analysis, guarded model step),
0009 (fixed LangGraph sequence, status only in nodes, allowlisted checkpoints).
