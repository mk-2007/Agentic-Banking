# Code tour: what each part is and what it does

Read `docs/how-it-works.md` first for the story. This file is the map from that story to the code, so you know
where to look and what to edit. Paths are from the repository root. Everything Python lives in
`backend/src/nexa/`.

## 1. One case, from click to close (follow it in this order)

| Step | What happens | Where |
|---|---|---|
| 1 | The browser calls `POST /cases` with a token. | `api/static/index.html`, `api/app.py` |
| 2 | The token becomes a `Principal` (user, role, channel). Employees only. | `api/principals.py` |
| 3 | `CaseService.open_case` checks the alert matches the bank's records, creates a `Case` and a `CaseScope` (which customer and accounts this case may touch), then runs the graph. | `api/service.py` |
| 4 | The **case graph** (LangGraph) runs a fixed sequence of nodes: `open_case` → `gather` → `analyze` → `research` → `verify` → `mark_ready` → `propose` → `request_approval` → `await_votes` → `settle` → `execute`. Each node runs one agent or one check and moves the case to its next status. | `orchestration/graph.py` (wiring), `orchestration/nodes.py` (the steps) |
| 5 | `gather`: **DataAgent** calls read tools and records the facts as evidence. | `agents/data_agent.py`, `agents/dossier.py` |
| 6 | `analyze`: **AnalysisAgent** does arithmetic over the history and emits findings from the closed code list. | `agents/analysis_agent.py`, `agents/findings.py`, `domain/indicators.py` |
| 7 | `research`: **PolicyAgent** searches the knowledge base for the clauses that apply. | `agents/policy_agent.py` |
| 8 | `verify`: **VerificationAgent** re-checks the findings and sets uncertainty flags. | `agents/verification_agent.py` |
| 9 | `propose`: a **DecisionProvider** ranks the closed set of actions; the **gates** can overrule it. Result is a `Decision` (a recommendation only). | `decision/rules.py`, `decision/llm_provider.py`, `decision/gates.py` |
| 10 | `request_approval`: if the action needs humans, an `ApprovalRequest` is created from the approval matrix and the case pauses (`waiting_for_approval`). | `orchestration/nodes.py`, `config/approval_matrix.py`, `approvals/store.py` |
| 11 | A person votes: `POST /cases/{id}/votes`. The role comes from the token. `resume_case` continues the paused graph. | `api/app.py`, `api/service.py` (`vote`), `domain/approval.py` |
| 12 | `settle` turns votes into a status (pure function). If approved, `execute` runs. | `domain/approval.py` (`evaluate_approval`), `orchestration/nodes.py` |
| 13 | **Executor tool** checks the approval is approved, in time and unused, consumes it, then changes the bank. | `tools/execution.py`, `security/approval_gate.py` |
| 14 | Every step above wrote an audit event, hash-chained to the previous one. | `audit/recorder.py`, `audit/log.py`, `domain/audit.py`, `domain/hashing.py` |

## 2. The packages, bottom to top

Dependencies point downward only: a lower package never imports a higher one (a test enforces this).

| Package | What it is | Key files |
|---|---|---|
| `domain` | Pure data types and rules shared by everyone: `Case` and its state machine, `Decision`, `Evidence`, approvals, audit events, roles, the closed action list and the finding codes. No I/O. | `case.py`, `decision.py`, `actions.py`, `indicators.py`, `approval.py` |
| `config` | Numbers and tables, not logic: fraud thresholds, who must approve what, which role may call which tool, who may read which knowledge. | `thresholds.py`, `approval_matrix.py`, `tool_permissions.py`, `rag_access.py`, `llm.py` |
| `bank_sim` | The fake bank (customers, accounts, transactions, KYC), loaded from `data/synthetic/`. A real bank would implement the same `BankGateway` interface. | `gateway.py`, `in_memory.py`, `seed.py`, `scenarios.py` |
| `security` | Deny-by-default role permissions, case scoping, and the check that an approval really authorizes an execution. | `permissions.py`, `scope.py`, `approval_gate.py` |
| `audit` | Append-only, tamper-evident event log. | `log.py`, `recorder.py` |
| `approvals` | In-memory store of approval requests, votes and single-use consumption. | `store.py` |
| `rag` | Knowledge base search (BM25), with access filtering applied before ranking. | `knowledge_base.py`, `ingest.py`, `bm25.py` |
| `tools` | The only door from agents to the bank. Every call goes through `ToolRegistry.invoke`, which applies permissions, case scope and audit. One tool writes (the executor); the rest only read. | `registry.py`, `read_tools.py`, `execution.py`, `knowledge.py` |
| `llm` | One gateway over model providers (Groq, Gemini via an OpenAI-compatible adapter). Validates model output, bounds retries, tracks cost. Models are never trusted. | `gateway.py`, `openai_compat.py`, `prompts.py`, `fake.py` |
| `agents` | The four specialists. They use tools, never the bank, and pass typed findings, never prose. | `data_agent.py`, `analysis_agent.py`, `policy_agent.py`, `verification_agent.py` |
| `decision` | Turns findings into a ranked recommendation. Rule-based or LLM provider; the same gates apply to both. | `rules.py`, `gates.py`, `llm_provider.py` |
| `orchestration` | The LangGraph workflow, the case state it carries, loop limits, and which types may be saved in a checkpoint. | `graph.py`, `nodes.py`, `state.py` |
| `api` | Thin HTTP layer plus the dashboard page. `service.py` wires everything together. | `app.py`, `service.py`, `schemas.py`, `static/index.html` |

## 3. "I want to change X": where to edit

| I want to... | Edit | Also touch |
|---|---|---|
| Change a fraud threshold (e.g. what counts as a rapid series) | `config/thresholds.py` | the matching number in `data/policies/NB-POL-FRAUD-001...md` (a test keeps them identical) |
| Change who must approve an action, or how long it stays valid | `config/approval_matrix.py` | `data/policies/NB-POL-AUTH-001...md` |
| Change what a role may call | `config/tool_permissions.py` | `tests/security/` |
| Change which action a pattern leads to | `decision/rules.py` | `docs/decision.md`, tests in `tests/unit/decision/` |
| Add or tighten a safety check on recommendations | `decision/gates.py` | tests |
| Add a new finding (a new fraud signal) | `domain/indicators.py`, then compute it in `agents/analysis_agent.py`, then let `decision/rules.py` use it | `agents/verification_agent.py` (so it can be re-checked), `data/agent_eval/expectations.json` |
| Add a new action (e.g. "limit card") | `domain/actions.py`, a rule in `decision/rules.py`, an entry in `config/approval_matrix.py`; to make it actually executable, add it to `EXECUTABLE_ACTIONS` and a branch in `tools/execution.py` (today only freeze account and block card execute) | `docs/security-model.md` |
| Add a scenario | `scripts/generate_synthetic_data.py` (then re-run it to rewrite `data/synthetic/`) | `data/agent_eval/expectations.json` |
| Change a policy or the bank's knowledge | `data/policies/` or `data/knowledge_base/` | `config/rag_access.py` for who may see it |
| Change the model or provider | `.env` (copy `.env.example`), `config/llm.py` | `llm/factory.py` |
| Change how the dashboard looks or behaves | `backend/src/nexa/api/static/index.html` | nothing else, it is one dependency-free file |
| Add an API endpoint | `api/app.py`, `api/schemas.py`, `api/service.py` | `docs/api.md` |
| Add a whole new package | create it with a docstring | a `module:` node in `docs/context/graph.json` and a rule in `tests/architecture/test_layer_rules.py`, or the architecture tests fail |

## 4. Watching it work without the browser

Run these from the repository root (they run offline with no key):

| Command | Shows |
|---|---|
| `python scripts/run_case.py scenario_f_account_takeover` | one scenario through the graph, printed step by step. The best way to see the pipeline. |
| `python scripts/run_case.py --all` | all scenarios |
| `python scripts/run_demo.py` | the whole demo through the HTTP API, with pass/fail checks |
| `python scripts/run_agent_eval.py` | the four agents checked against `data/agent_eval/expectations.json` |
| `python scripts/run_decision_eval.py` | rule provider and deliberately misbehaving stand-in models scored on safety |
| `python scripts/run_api.py --demo` | the server and dashboard, with demo tokens |

While the server runs, `http://127.0.0.1:8000/docs` is an interactive page for every endpoint.

## 5. Habits that keep changes safe

1. Run `pytest -q` from `backend/`. Architecture tests fail if a layer rule or the graph file drifts.
2. Authorization stays in plain code (`security/`, `tools/`, `decision/gates.py`). Never move a permission
   decision into a prompt.
3. Agents never import `bank_sim`. They reach it only through `tools`.
4. Third-party text (merchant names, memos) never goes into findings or prompts.
5. Case status changes only inside the orchestration nodes, through `Case.transition_to`.
6. After a change, update `docs/PROJECT_LOG.md` and `docs/context/graph.json` (see `AGENTS.md`, section 4).
