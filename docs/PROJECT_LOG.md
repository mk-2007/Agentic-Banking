# Project log

Newest first. Add an entry whenever a step is finished or a decision is made.

## 2026-10-14 - Phase 5b: specialist agents with scenario evals
- `agents`: data, analysis, policy and verification agents, plus `ToolSession` (tool calls under the agent's own role, case and a channel set by trusted code). Findings are evidence with a closed code set (ADR 0008). Analysis is plain code against the policy thresholds, judged on history before the suspicious burst. Verification recomputes each finding and sets the insufficient / conflicting evidence flags. The policy agent may use a model only to narrow retrieved clauses; any failure keeps every clause.
- Policy topics count as covered only when their governing policy was retrieved, so a customer-channel session reports gaps instead of using weaker material.
- Config: two card-testing thresholds added to `FraudThresholds` and to NB-POL-FRAUD-001 (a test keeps them in sync). `Contract` no longer triggers pydantic's protected-namespace warning. Default Gemini model is now `gemini-flash-latest` (the 2.5 name returned not-found; four flash models answered 503 overloaded, so Gemini still has no successful call).
- Evaluation: `data/agent_eval/expectations.json`, harness under `backend/tests/evals/`, `scripts/run_agent_eval.py`. 7 of 7 scenarios pass offline; the harness was mutation-tested. 487 tests pass; ruff and mypy clean.
- Next: Phase 6, LangGraph orchestration with the human approval pause. Not yet run: the model step against a live provider.

## 2026-10-16 - Phase 6b: human approval pause (issue #15)
- `orchestration`: with a decision source the graph goes `propose -> request_approval -> await_votes -> settle`. A Level 3+ recommendation saves the run at `waiting_for_approval`; `resume_case` continues it with votes, and the pure `evaluate_approval` rule picks the status (approved, rejected, escalated, timed out, modify, or still pending). Orchestration builds the request from the approval matrix, never the decision source.
- A decision for another case, or one that drops a blocking uncertainty flag from verification, ends in `blocked_by_policy`. Pausing requires a checkpointer. Decision, approval and role types joined the checkpoint allowlist.
- 523 tests pass (15 new), including a resume from a freshly built graph with nothing refused by the serializer.
- Not built: executing the approved action (6d), limits and audit per transition (6c), who-voted authentication (8a).

## 2026-10-16 - Phase 7b: LLM decision provider
- `decision.LlmDecisionProvider`: a model ranks actions and cites evidence (schema-validated, closed action set); the shared gates (`decision/gates.py`: uncertainty, no-action, justification) walk its ranking and the first allowed action wins, with `overridden_by` naming a skipped pick. Policy references come from retrieval, never the model; scores come from rank and confidence; confidence is stored uncalibrated and flagged below 0.5. Prompt carries codes, signals and ids only.
- Any model failure falls back to the rule provider and the decision says so (`provider`). New `no_action_gate` applies to both providers. `facts.py` holds the shared finding reader.
- 619 tests pass (26 new). Removing the justification gate, the error fallback or the id check each fails tests. Only a scripted model has been used; real-model behaviour is 7c.

## 2026-10-16 - Phase 7a: rule-based decision provider
- `decision`: `DecisionProvider` protocol, `DecisionRequest` and `RuleBasedDecisionProvider`. Seven rules map typed findings to one action each, ranked by fixed scores; two hard gates choose the recommendation: blocking uncertainty allows only cautious actions, and a Level 3+ action needs supporting findings plus a clause from the document that governs it. A skipped top candidate is named in `overridden_by`.
- `IndicatorCode`, `Signal` and `SIGNAL_OF` moved to `domain/indicators.py` (agents re-export them) because the decision layer may not import agents.
- `orchestration.provider_source` plugs a provider into the graph. All seven scenarios get an acceptable action; an account takeover runs from alert to a frozen account through two humans. 593 tests pass (39 new); disabling the uncertainty gate or lowering the takeover threshold fails tests.
- Design choice: no recognisable findings at all means escalate, not "no action", because nothing was assessed.
- Not built: LLM provider (7b), scoring harness (7c), comparison write-up (7d).

## 2026-10-16 - Phase 6d: execution of approved actions
- `approvals.InMemoryApprovalStore` (requests, votes, atomic single-use consumption; implements `security.ApprovalSource`). New `execute` step after an approved `settle`: calls the guarded tool as the execution service, then `approved -> executed -> verified -> completed`; a refusal ends `failed_tool`, an effect that did not show ends `failed_validation`.
- Tests: Level 4 with two approvers, Level 3 with one, one approver only, reject/escalate/modify, expiry, replay, approval consumed elsewhere, no store configured, and all seven scenarios end to end with no change to the bank without approval. 554 tests pass; routing around `execute` or ignoring a refusal each fail tests.
- Limits: the store is in memory and does not authenticate approvers (8a); verification trusts the tool's own output because the execution role cannot read accounts.

## 2026-10-16 - Phase 6c: limits, retries and audit
- `orchestration.limits`: `RunLimits` (2 attempts per step, 5 vote rounds). A temporary tool failure (`timeout`, `internal_error`) goes `executing -> waiting_for_tool -> executing` and retries once; refusals are never retried. A case that stays pending too long ends `escalated` (`approval:too_many_rounds`).
- Optional `AuditRecorder` on the graph: the orchestrator writes `case_created`, a `state_changed` per transition, `decision_made`, `approval_requested`, `approval_vote_cast` and `error` (with the failure code). Nothing is written without a recorder.
- 534 tests pass (11 new); disabling the transient codes fails three of them.
- Not built: loop-back to gather when records are missing; scenario A-F orchestration tests (6d).

## 2026-10-14 - Phase 6a: case graph
- `orchestration`: a LangGraph graph runs a case through open, gather, analyze, research and verify, then `decision_ready` or `failed_validation`; a refused tool or inconsistent records end in `failed_tool` with a short code. The status changes only in the nodes, via `Case.transition_to` (ADR 0009). `AgentSet` lets tests swap in failing agents.
- Checkpointing is prepared for 6b: state is contracts and lists only (`PolicyResult` became a contract so its tuples survive), and `checkpoint_serde()` rebuilds only an explicit allowlist of our types, as LangGraph recommends. Proven with an in-memory saver; a test fails if a state type is missing from the list.
- `langgraph>=1.2,<2` added as a dependency. Shared test fixtures moved to `backend/tests/support`. `scripts/run_case.py` runs scenarios through the graph. 508 tests pass (21 new); the checks were mutation-tested (dropping an allowlisted type, ignoring a failed verification, not catching tool errors each fail a test).
- Not built yet: approval pause (6b); loop limits, retries and an audit event per transition (6c); decisions (Phase 7). See docs/orchestration.md.

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
