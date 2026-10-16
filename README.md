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
| 2 | Simulated bank, synthetic data, policy documents, approval matrix | done |
| 3 | Security, audit and tool layer (before any LLM) | done |
| 4 | RAG over knowledge base and policies | done |
| 5 | Model gateway (5a) and specialist agents with scenario evals (5b) | done |
| 6 | LangGraph orchestration with human approval (6a case graph, 6b approval pause and 6c limits and audit done; 6d execution of approved actions done; merging the stacked PRs next) | in progress |
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
| `data/` | `synthetic/` bank data + scenarios, `policies/` synthetic policy documents, `knowledge_base/` corpus, synonyms and retrieval evaluation set, `agent_eval/` expectations for the agent scenarios |
| `scripts/` | `generate_synthetic_data.py`, `github_bootstrap.sh`, `llm_smoke_test.py`, `run_agent_eval.py`, `run_case.py` |

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

## Simulated bank and data

Phase 2 adds a deterministic simulated bank behind gateway interfaces, 865 synthetic transactions,
three synthetic policy documents, the fraud thresholds and approval matrix as configuration, and seven
evaluation scenarios (PRD A-E plus an account-takeover and a prompt-injection case). See
[docs/synthetic-data.md](docs/synthetic-data.md).

## Security model

Phase 3 makes the guarantees real, with no LLM involved: deny-by-default tool permissions from a config
matrix, per-case data scoping, data minimisation, a hash-chained append-only audit log, and a single
guarded execution tool that needs a valid, single-use approval. Scenario E is now a passing test. See
[docs/security-model.md](docs/security-model.md), including its list of honest limits.

## Knowledge retrieval

Phase 4 ingests the knowledge base and policy documents into 98 cited chunks and searches them with BM25.
Access is decided **before ranking**: one index per clearance level, and the clearance is the stricter of the
caller's role and the session channel, so a customer chat can never reach internal or restricted material.
On 40 labelled questions the right section is in the top 3 for 92.5%, with the caveats in
[docs/rag.md](docs/rag.md).

## Model gateway

Phase 5a adds one adapter for any OpenAI-compatible provider (Groq and Gemini presets), with retries, automatic
failover between providers, a per-case token budget, and structured output that is validated against a schema
before anyone uses it. Setup and limits: [docs/llm-gateway.md](docs/llm-gateway.md). To try your own keys:
copy `.env.example` to `.env`, then `python scripts/llm_smoke_test.py`.

## Specialist agents

Phase 5b adds four agents that reach the bank only through tools: data, analysis, policy and verification.
They exchange typed findings from a closed vocabulary, not prose. Analysis is plain code over the policy
thresholds, and verification recomputes every finding before anyone decides on it. A model is used in one
place (narrowing retrieved policy clauses) and can never widen anything. All seven scenarios pass offline:
`PYTHONPATH=backend/src python scripts/run_agent_eval.py`. Design and honest limits:
[docs/agents.md](docs/agents.md).

## Case orchestration

Phase 6a runs a case through a LangGraph graph (6b adds the human approval pause: a Level 3+ recommendation saves the run and waits for votes, judged by the pure approval rule): open, gather, analyze, research, verify, then `decision_ready`
or a clear failure state. 6c bounds every loop (one retry for temporary tool failures, escalation after too many vote rounds) and writes an audit event for every transition. The case status changes only inside the graph, and a refused tool or a forged finding
ends the run cleanly with a code. Saved cases come back with their types intact and can only be rebuilt from an
explicit list of our own types. Try it with `PYTHONPATH=backend/src python scripts/run_case.py --all`. Design,
gaps and limits: [docs/orchestration.md](docs/orchestration.md).

## Decisions so far

- [ADR 0001](docs/adr/0001-layered-architecture-and-tool-layer-enforcement.md): layered architecture; the tool layer enforces security.
- [ADR 0002](docs/adr/0002-swappable-decision-provider.md): the decision layer is a swappable provider; no JEV dependency (we have no access).
- [ADR 0003](docs/adr/0003-safety-invariants-live-in-the-contracts.md): safety invariants are enforced by the domain contracts themselves.
- [ADR 0004](docs/adr/0004-bank-access-through-gateway-protocols.md): bank access goes through gateway Protocols; synthetic data is deterministic.
- [ADR 0005](docs/adr/0005-tool-layer-enforces-deny-by-default-and-single-use-approvals.md): deny by default; approvals are single-use and bound to one target.
- [ADR 0006](docs/adr/0006-filter-knowledge-before-ranking-and-fail-closed-channel.md): knowledge is filtered before ranking; the session channel is trusted input that fails closed.
- [ADR 0007](docs/adr/0007-one-compatible-adapter-and-never-trust-model-output.md): one OpenAI-compatible adapter; the gateway owns reliability; model output is never trusted.
- [ADR 0008](docs/adr/0008-typed-findings-deterministic-analysis-and-a-guarded-model-step.md): agents exchange typed findings; analysis is deterministic; the one model step is guarded.
- [ADR 0009](docs/adr/0009-fixed-langgraph-sequence-status-only-in-nodes-allowlisted-checkpoints.md): a fixed LangGraph sequence; status changes only in nodes; checkpoints rebuild only listed types.

## Scope and limits

Prototype only: synthetic data, no real banking systems, no production encryption. The design aims
to scale by swapping `bank_sim` for a real gateway behind the same tool interface.
