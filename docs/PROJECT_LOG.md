# Project log

Newest first. Add an entry whenever a step is finished or a decision is made.

## 2026-10-14 - Phase 5b: specialist agents with scenario evals
- `agents`: data, analysis, policy and verification agents, plus `ToolSession` (tool calls under the agent's own role, case and a channel set by trusted code). Findings are evidence with a closed code set (ADR 0008). Analysis is plain code against the policy thresholds, judged on history before the suspicious burst. Verification recomputes each finding and sets the insufficient / conflicting evidence flags. The policy agent may use a model only to narrow retrieved clauses; any failure keeps every clause.
- Policy topics count as covered only when their governing policy was retrieved, so a customer-channel session reports gaps instead of using weaker material.
- Config: two card-testing thresholds added to `FraudThresholds` and to NB-POL-FRAUD-001 (a test keeps them in sync). `Contract` no longer triggers pydantic's protected-namespace warning. Default Gemini model is now `gemini-flash-latest` (the 2.5 name returned not-found; four flash models answered 503 overloaded, so Gemini still has no successful call).
- Evaluation: `data/agent_eval/expectations.json`, harness under `backend/tests/evals/`, `scripts/run_agent_eval.py`. 7 of 7 scenarios pass offline; the harness was mutation-tested. 487 tests pass; ruff and mypy clean.
- Next: Phase 6, LangGraph orchestration with the human approval pause. Not yet run: the model step against a live provider.

## 2026-10-14 - Process: tracker, resume-state and workflow
- Added `docs/TRACKER.md` (phase dates, test counts, remaining work split into PR-sized steps, open items, PR log), `docs/context/STATE.md` (resume-here snapshot) and `docs/WORKFLOW.md` (small branches, small green commits, merge commits). The PR template now asks for the tracker and state updates.

## 2026-10-13 - Phase 5a-3: gateway diagnostics after the first live run
- Live smoke test: Groq `openai/gpt-oss-20b` succeeded (655 ms, no repairs). Gemini `gemini-2.5-flash` was listed but the chat endpoint returned not found.
- 404 errors now include the provider's own explanation; failover summaries no longer repeat the provider name; model ids with a `models/` prefix are accepted; smoke script gained `--model PROVIDER=MODEL` and prints clean ids.
- 446 tests pass. Gemini default model to be settled once a working model is confirmed.

## 2026-10-13 - Phase 5a: model gateway
- `llm`: provider-neutral types, one OpenAI-compatible adapter (Groq and Gemini presets), retries with backoff, failover, per-case token budget, validated structured output with bounded repair, untrusted-text fencing, environment factory, scripted fake provider (ADR 0007).
- Errors are redacted so API keys can never appear in messages; a model that rejects `response_format` is retried without it.
- `scripts/llm_smoke_test.py` lists the models a key can use and makes one validated call per provider. Not yet run against live APIs.
- Renamed a module that shadowed the standard library (`types` -> `messages`) before it spread.
- 443 tests pass. Next: Phase 5b, specialist agents with small evals.

## 2026-10-12 - Phase 4: RAG
- Converted the knowledge base to Markdown with front matter; labelled sections 13/17/18/19 internal and the fraud and AML policies restricted.
- `rag`: parsing, chunking (FAQ pairs, split tables, packed lists), version resolution, dependency-free BM25, synonym expansion; 98 chunks.
- Access control before ranking: one index per clearance level; clearance = stricter of role and session channel (ADR 0006). Channel is set by trusted code on `ToolCall` and defaults to customer.
- New `search_knowledge_base` tool: cited passages, historical documents for employee sessions only, audit records which policy versions were consulted.
- New domain pieces: `Sensitivity`, `Chunk`, `SessionChannel`, `Role.CUSTOMER_SERVICE_AGENT`.
- Evaluation: 40 labelled questions, recall@3 0.925, MRR 0.90 (caveats in docs/rag.md). Two synonym groups were added after the first run exposed vocabulary gaps.
- A test caught chunk ids colliding across document versions; ids now include the version.
- 381 tests pass. Next: Phase 5, model gateway and specialist agents.

## 2026-10-11 - Phase 3: security, audit and tool layer
- `security`: role check (deny by default), per-case scope for agents, approval gate (one action, one account, one case, once, unexpired).
- `config`: tool permission matrix is the single source of truth; tools that differ cannot register.
- `audit`: append-only log with JSONL persistence; reopening a tampered file raises `AuditTamperedError`.
- `tools`: registry (authorize, audit before/after, error handling), five privacy-minimised read tools, one guarded execution tool.
- Scenario E passes: a data agent's freeze attempt is refused and recorded. Replay, wrong account/case/action, missing second approver, rejection and expiry are all refused.
- Domain changes: `Role.EXECUTION_SERVICE`, `ApprovalRequest.target_account_id`, `AuditEventType.TOOL_COMPLETED`, `Clock` (ADR 0005).
- 256 tests pass. Next: Phase 4, RAG over the knowledge base and policy documents.

## 2026-10-10 - Phase 2: simulated bank, data and policies
- Added `bank_sim`: record models, `BankGateway` Protocols (customer, account, transaction, KYC, actions) and a deterministic in-memory bank (ADR 0004).
- Added `config`: fraud thresholds and the approval matrix (Level 4 = fraud analyst + risk officer; expiries 60/120/240 minutes).
- Added a deterministic data generator and committed dataset (23 customers, 865 transactions); a test regenerates it to prove it matches.
- Defined 7 scenarios as data: PRD A-E plus F (account takeover, Level 4 approval) and X (prompt injection).
- Wrote 3 synthetic policy documents with KB section 19.2 metadata; a test keeps their numbers identical to config.
- 107 tests pass. Next: Phase 3, security + audit + tool layer (before any LLM).

## 2026-10-09 - Phase 1: domain contracts
- Added immutable, strict contracts: actions/risk, actors, evidence, case state machine, decision, approval, tool, audit.
- Safety rules are validators (ADR 0003): unsafe decisions cannot be constructed; Level 4 needs two approver roles; audit events form a hash chain.
- Renamed Level 3/4 actions to `block_card` / `freeze_account` (the action itself; a decision recommends it, a human authorizes it).
- 68 tests pass (unit + architecture). GitHub project scaffolding (templates, labels, seeded issues) lands in a separate PR.
- Next: Phase 2, simulated bank, synthetic data and the fraud/approval policy document.

## 2026-10-09 - Phase 0: scaffold
- Chose the investigation workflow: suspicious-transaction investigation ending in a Level 4 account-freeze recommendation.
- Decided to build without JEV (no access); decision layer is a swappable provider (ADR 0002).
- Created repo layout, tooling (ruff, mypy strict, pytest), CI, architecture tests, context graph.
- Next: Phase 1, domain contracts.
