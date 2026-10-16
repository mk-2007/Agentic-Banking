# Progress tracker

The single place to see what is done, what is next and whether the schedule holds. Update it in the
**same pull request** as the work (the PR template asks). Newest facts win; history lives in
[PROJECT_LOG.md](PROJECT_LOG.md).

**Hackathon deadline:** `18-10-2026:__` (fill this in; every "days left" below depends on it)
**Last updated:** 2026-10-16

## Phases

| Phase | Scope | Started | Done | Days taken | Tests | Status |
|---|---|---|---|---|---|---|
| 0 | Scaffold, tooling, CI, architecture tests, context graph | 2026-10-09 | 2026-10-09 | 1 | n/a | done |
| 1 | Domain contracts with safety invariants | 2026-10-09 | 2026-10-09 | 1 | 68 | done |
| 2 | Simulated bank, synthetic data, policies, approval matrix | 2026-10-10 | 2026-10-10 | 1 | 107 | done |
| 3 | Security, audit and tool layer | 2026-10-11 | 2026-10-11 | 1 | 256 | done |
| 4 | RAG over knowledge base and policies | 2026-10-12 | 2026-10-12 | 1 | 381 | done |
| 5a | Model gateway (Groq, Gemini, failover, budgets) | 2026-10-13 | 2026-10-13 | 1 | 446 | done (Gemini never succeeded live) |
| 5b | Specialist agents + scenario evals | 2026-10-14 | 2026-10-14 | 1 | 487 | done |
| 6 | LangGraph orchestration, approval pause, loop limits | 2026-10-14 | | est. 2-3 | 554 so far | in progress (6a-6d built; PRs #33, #34 and 6d open) |
| 7 | Decision providers (rule-based, LLM), baseline vs LLM evaluation | 2026-10-16 | | est. 2-3 | 593 so far | in progress (7a done) |
| 8 | API, frontend, demo | | | est. 3-4 | | planned |

"Days taken" and "Tests" for finished phases come from the project log (calendar days, not hours; tests are the count when the phase closed).
"est." figures are **my estimates** from the pace of phases 0-5, not measurements; correct them as
real numbers arrive. Rough remaining effort: 7 to 10 calendar days at the current pace. Keep at least
2 days of buffer before the deadline for the demo and for things that break.

## Proposed split of the remaining phases (each line = one pull request)

**Phase 6**
- [x] 6a Case state machine as a LangGraph graph, wiring the four agents (no approvals yet)
- [x] 6b Approval interrupt and resume, using the existing approval contracts (closes #15)
- [x] 6c Loop limits, tool-failure states, audit events for every transition
- [x] 6d Execution of approved actions, and orchestration tests for scenarios A-F, X (including the Level 4 two-approver path)

**Phase 7**
- [x] 7a Rule-based decision provider (ranked candidate actions, policy refs, uncertainty respected)
- [ ] 7b LLM decision provider behind the same interface, validated like every model output
- [ ] 7c Evaluation harness: score both providers on the seven scenarios
- [ ] 7d Baseline vs LLM comparison written up in docs

**Phase 8**
- [ ] 8a API (cases, evidence, approvals) with the employee/customer channel decided by trusted code
- [ ] 8b Frontend: case view, evidence, approval screen
- [ ] 8c Demo script, seeded run, screenshots or short video
- [ ] 8d Final README, honest-limits pass, release tag

## Open items

| Item | Owner | Since | Note |
|---|---|---|---|
| Gemini has no successful live call | you | 2026-10-13 | 503 overloaded on 4 models; re-run `python scripts/llm_smoke_test.py` |
| Model step in the policy agent never run live | you | 2026-10-14 | `python scripts/run_agent_eval.py --live` |
| Repo public| synthetic data only, no keys |
| Deadline above | you | | Fill in at the top |

## Pull request log

Add one row per merged PR. This is also the proof of work for judges.

| PR | Branch | Merged | What |
|---|---|---|---|
| #1 | chore/github-project-setup | 2026-10-09 | Chore/GitHub project setup |
| #2 | feat/phase-1-domain-contracts | 2026-10-09 | Feat/phase 1 domain contracts |
| #22 | feat/phase-2-simulated-bank | 2026-10-10 | Phase 2: simulated bank, synthetic data and policies |
| #23 | feat/phase-3-security-audit-tools | 2026-10-11 | Feat/phase 3 security audit tools |
| #24 | feat/phase-4a-rag-core | 2026-10-11 | Feat/phase 4a rag core |
| #25 | feat/phase-4b-knowledge-tool | 2026-10-11 | Feat/phase 4b knowledge tool |
| #26 | feat/phase-5a1-gateway-core | 2026-10-13 | hase 5a-1: model gateway core (Groq and Gemini adapter, retries, failover, budget, structured output) |
| #27 | feat/phase-5a2-smoke-test-and-docs | 2026-10-13 | Phase 5a-2: live smoke test, .env template and gateway docs |
| #28 | feat/phase-5a3-gateway-diagnostics | 2026-10-13 | Phase 5a-3: gateway diagnostics after the first live run |
| #29 | feat/phase-5b-specialist-agents | 2026-10-14 | feat(agents): specialist agents with scenario evals (phase 5b) |
| #30 | docs/tracker-5b-merged | 2026-10-14 | docs(tracker): record phase 5b merge and PR history |
| #31 | feat/phase-6a-case-graph | 2026-10-16 | feat(orchestration): LangGraph case graph (phase 6a) |