# NexaBank Agentic Platform

An **agentic environment for banking**: not just a chatbot, but a controlled system where specialist
AI agents investigate cases, ground their answers in bank policy, recommend actions, and hand risky
decisions to humans. Built as a hackathon prototype on **synthetic data**, designed so a real bank
gateway can replace the simulator later.

**Priorities, in order:** security and privacy, precise decision-making, auditability, cost.

> This README is kept current. See [Status](#status) for what exists today and
> [docs/PROJECT_LOG.md](docs/PROJECT_LOG.md) for the history.

## Status

| Phase | What | State |
|---|---|---|
| 0 | Scaffold, tooling, CI, architecture tests, context graph | done |
| 1 | Domain contracts (case, evidence, decision, approval, tool, audit) with safety invariants | done |
| 2 | Simulated bank, synthetic data, policy document | next |
| 3 | Security, audit and tool layer (before any LLM) | planned |
| 4 | RAG over knowledge base and policies | planned |
| 5 | Specialist agents with small evals | planned |
| 6 | LangGraph orchestration with human approval | planned |
| 7 | Decision providers and evaluation | planned |
| 8 | API, frontend, demo | planned |

## Core idea: controlled autonomy

Agents **recommend**; deterministic code and humans **authorize**. Actions are risk-levelled 1 to 4;
Level 4 (for example freezing an account) needs two human approvers. Agents never touch the bank
directly: every access passes through a tool layer that enforces permissions and writes the audit log.

```
 request/alert -> api -> orchestration (LangGraph)
                              |
        supervisor -> data / policy / analysis agents   (via tools, rag)
                              |
                      verification -> decision (ranked candidate actions)
                              |
                  security (risk level, approvers) -> approvals (human)
                              |
                    tools.execute (approved ID only) -> audit log
```

## Repository map

| Path | Purpose |
|---|---|
| `backend/src/nexa/` | The platform, one package per layer (see [architecture](docs/architecture.md)) |
| `backend/tests/` | `architecture/` (layer + graph guards), `unit/`, `integration/`, `scenarios/`, `security/` |
| `docs/source/` | Original PRD and NexaBank knowledge base |
| `docs/adr/` | Architecture decision records: why things are the way they are |
| `docs/context/graph.json` | Machine-readable project memory for AI agents |
| `AGENTS.md` | Operating manual for AI agents working here |
| `data/` | Synthetic customers/transactions and policy documents |

## Quickstart

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q          # tests, including architecture rules
ruff check . && ruff format --check . && mypy
```

## Dependency rule

Lower layers never import higher ones, and agents cannot import the bank simulator. The rule is
a test (`backend/tests/architecture/test_layer_rules.py`), so CI fails if it is broken.

## Project memory for other agents

`docs/context/graph.json` records modules, phases, decisions and how they relate; `AGENTS.md`
explains how to use and update it. A test fails if the graph drifts from the code.

## Domain contracts

Phase 1 defines the data models and safety rules every layer shares: a closed set of actions, a case
state machine, a decision object that cannot be built unsafely, approval evaluation, and a
tamper-evident audit chain. See [docs/domain-contracts.md](docs/domain-contracts.md).

## Decisions so far

- [ADR 0001](docs/adr/0001-layered-architecture-and-tool-layer-enforcement.md): layered architecture; the tool layer enforces security.
- [ADR 0002](docs/adr/0002-swappable-decision-provider.md): the decision layer is a swappable provider; no JEV dependency (we have no access).
- [ADR 0003](docs/adr/0003-safety-invariants-live-in-the-contracts.md): safety invariants are enforced by the domain contracts themselves.

## Scope and limits

Prototype only: synthetic data, no real banking systems, no production encryption. The design aims
to scale by swapping `bank_sim` for a real gateway behind the same tool interface.
