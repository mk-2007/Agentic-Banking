# Status (generated; do not edit)

Regenerate with `python scripts/gen_status.py`. Other documents link here for current numbers.

- **Tests:** 854 collected
- **Architecture decision records:** 16
- **Latest release tag:** v0.1.0; built from commit a4aa9bf
- **Latest randomised-traffic run:** saved 2026-10-18T12:39:06+00:00, provider anthropic, [1, 2] seeds, 288 s

| Phase | Status | Summary |
|-------|--------|---------|
| phase:0 | done | Scaffold, tooling, CI, architecture tests, context graph |
| phase:1 | done | Domain contracts: schemas for case, evidence, decision, tool, audit |
| phase:2 | done | bank_sim + synthetic data + policy document for scenarios A-E and injection case |
| phase:3 | done | security + audit + tools layer with tests (before any LLM) |
| phase:4 | done | RAG: ingestion, chunking, per-clearance BM25 retrieval, knowledge search tool |
| phase:5 | done | 5a model gateway and 5b specialist agents with scenario evals done |
| phase:6 | done | LangGraph orchestration, approval interrupt, loop limits |
| phase:7 | done | Decision providers wired in; baseline vs LLM evaluation |
| phase:8 | done | API, frontend, evaluation report, demo script |

Open work is in [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md).
