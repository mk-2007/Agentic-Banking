#!/usr/bin/env bash
# Seeds labels, milestones and issues for the project roadmap using the GitHub CLI (gh).
#
# Prerequisites: install gh (https://cli.github.com), run `gh auth login`, and run this
# from inside the cloned repository. Safe to re-run: existing labels are updated,
# milestones that already exist are skipped, and issues with the same title are not duplicated.
set -euo pipefail

command -v gh >/dev/null || { echo "gh CLI not found. Install it from https://cli.github.com"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Not logged in. Run: gh auth login"; exit 1; }

echo "Creating labels..."
label() { gh label create "$1" --color "$2" --description "$3" --force >/dev/null; }
label "type:feature" "0e8a16" "New capability or planned task"
label "type:bug" "d73a4a" "Something is broken"
label "type:docs" "0075ca" "Documentation"
label "type:test" "fbca04" "Tests and evaluation"
label "area:security" "b60205" "Permissions, approvals, audit"
label "area:data" "5319e7" "Simulated bank and synthetic data"
label "area:rag" "1d76db" "Retrieval and policy knowledge"
label "area:agents" "006b75" "Agents and orchestration"
label "area:decision" "c2e0c6" "Decision layer"
label "area:frontend" "f9d0c4" "Dashboard and UI"
label "phase:2" "ededed" "Phase 2"
label "phase:3" "ededed" "Phase 3"
label "phase:4" "ededed" "Phase 4"
label "phase:5" "ededed" "Phase 5"
label "phase:6" "ededed" "Phase 6"
label "phase:7" "ededed" "Phase 7"
label "phase:8" "ededed" "Phase 8"

echo "Creating milestones..."
milestone() {
  gh api "repos/{owner}/{repo}/milestones" -f title="$1" -f description="$2" >/dev/null 2>&1 \
    || echo "  (milestone '$1' already exists, skipping)"
}
milestone "Phase 2: Simulated bank and data" "bank_sim, synthetic data, fraud and approval policy document"
milestone "Phase 3: Security, audit and tools" "Permission engine, audit log, tool layer, built before any LLM"
milestone "Phase 4: RAG" "Ingestion, chunking and metadata-filtered retrieval"
milestone "Phase 5: Agents" "Specialist agents with small evaluations"
milestone "Phase 6: Orchestration" "LangGraph graph, approval interrupt, loop limits"
milestone "Phase 7: Decision layer" "Decision providers and baseline evaluation"
milestone "Phase 8: API, UI and demo" "FastAPI, dashboard, evaluation report, demo script"

echo "Creating issues..."
EXISTING="$(gh issue list --state all --limit 500 --json title --jq '.[].title')"
issue() { # title milestone labels body
  if printf '%s\n' "$EXISTING" | grep -Fxq "$1"; then echo "  (skipping existing: $1)"; return; fi
  gh issue create --title "$1" --milestone "$2" --label "$3" --body "$4" >/dev/null
  echo "  created: $1"
}

M2="Phase 2: Simulated bank and data"
issue "Write synthetic fraud thresholds and approval matrix policy document" "$M2" "type:docs,area:data,phase:2" \
"Create a versioned synthetic policy document (metadata per KB section 19.2) covering fraud thresholds, AML/KYC escalation, account-freeze policy and who approves what.

- [ ] Document under data/policies/
- [ ] Approval matrix expressed as config (backend/src/nexa/config)
- [ ] Referenced from the README"
issue "Build bank_sim: customers, accounts, transactions, cases" "$M2" "type:feature,area:data,phase:2" \
"Simulated banking API behind the same interface a real gateway would use. Only tools may call it.

- [ ] Typed repositories for customer, account, transaction, case
- [ ] Seed loader with deterministic data
- [ ] Unit tests"
issue "Seed scenarios A-E from PRD section 44" "$M2" "type:feature,area:data,phase:2" \
"Deterministic synthetic datasets for each demo scenario, so tests and the demo always behave the same.

- [ ] One dataset per scenario
- [ ] Each scenario has an expected outcome documented"
issue "Add prompt-injection scenario to synthetic data" "$M2" "type:test,area:security,phase:2" \
"Place an instruction-like string in a merchant name or note field. Later phases must prove agents treat it as data, not as an instruction."

M3="Phase 3: Security, audit and tools"
issue "Implement permission engine and role matrix" "$M3" "type:feature,area:security,phase:3" \
"Plain-code authorization (ADR 0001). Tests first.

- [ ] Role to tool permission matrix in config
- [ ] Deny by default
- [ ] Tests for every role/tool combination"
issue "Implement append-only audit log using the hash chain" "$M3" "type:feature,area:security,phase:3" \
"Store AuditEvents sealed with the domain hash chain; expose verification.

- [ ] Append-only store
- [ ] Chain verification on read
- [ ] Tamper test"
issue "Build tool interface, registry and enforcement" "$M3" "type:feature,area:security,phase:3" \
"Every tool declares a ToolSpec; the registry checks permissions and writes audit events before and after execution.

- [ ] Registry with spec validation
- [ ] Denied calls produce TOOL_DENIED audit events
- [ ] execute_authorized_action accepts only an approved, unexpired approval"

M4="Phase 4: RAG"
issue "Ingest and chunk the NexaBank knowledge base with metadata" "$M4" "type:feature,area:rag,phase:4" \
"Chunk by section with metadata from KB section 19.2 (version, audience, sensitivity)."
issue "Metadata-filtered retrieval with audience and sensitivity rules" "$M4" "type:feature,area:rag,phase:4" \
"Customer-channel retrieval must never return employee-only or detection-logic content (KB section 17.6)."

M5="Phase 5: Agents"
issue "Implement data, policy and analysis agents with small evals" "$M5" "type:feature,area:agents,phase:5" \
"Each agent has one job and uses only its permitted tools. Add a small evaluation set per agent."
issue "Implement verification agent (claims must trace to evidence)" "$M5" "type:feature,area:agents,phase:5" \
"Reject any claim not backed by an Evidence record or policy clause."

M6="Phase 6: Orchestration"
issue "LangGraph orchestration with case state machine and loop limits" "$M6" "type:feature,area:agents,phase:6" \
"Graph follows the domain state machine; enforce max iterations, tool calls and token budget."
issue "Human approval interrupt and resume" "$M6" "type:feature,area:security,phase:6" \
"Pause at WAITING_FOR_APPROVAL; resume only through evaluate_approval."

M7="Phase 7: Decision layer"
issue "Rule-based DecisionProvider (baseline)" "$M7" "type:feature,area:decision,phase:7" \
"Deterministic scorer over structured evidence features, producing a valid Decision (ADR 0002)."
issue "LLM structured-output DecisionProvider" "$M7" "type:feature,area:decision,phase:7" \
"Same schema, validated, with retries on malformed output."
issue "Baseline vs provider evaluation on scenarios A-E" "$M7" "type:test,area:decision,phase:7" \
"Report accuracy, calibration, latency and cost per case."

M8="Phase 8: API, UI and demo"
issue "FastAPI routes for cases, approvals and chat" "$M8" "type:feature,phase:8" \
"Thin routes delegating to orchestration; no business logic."
issue "Dashboard: case view, agent activity, approval screen" "$M8" "type:feature,area:frontend,phase:8" \
"Show the audit trail and the reasoning behind each recommendation."
issue "Write demo script and evaluation report" "$M8" "type:docs,phase:8" \
"A repeatable demo using deterministic seeds, with cached fallbacks."

echo "Done."
