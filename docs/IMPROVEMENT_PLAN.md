# Improvement plan: from prototype to a credible bank-operations system

Every item names the limitation it solves (**L1-L10**), the smallest change that solves it at prototype
depth, what is deliberately left out, and how we know it works. We do one work package (WP) per branch and
PR, in the order below. Tests come first for anything touching security, audit or approvals.

Scope rule: this is a prototype. Each WP ships a **real, working slice behind an interface**, not a
production platform. Where a production system would need more, the WP says so under "Not done".

## Limitations

| ID | Limitation (as found in review) | Evidence in this repo |
|----|---------------------------------|-----------------------|
| L1 | Documentation drifts; there is no single authoritative status | `STATE.md` says 679 tests and "next: tag v0.1.0" while the log is at 2026-10-18 and v0.1.0 exists |
| L2 | State lives in memory: cases, checkpoints, approvals, audit are lost on restart | `InMemoryApprovalStore`, `InMemoryAuditLog`, in-memory checkpointer |
| L3 | Authentication is a pasted static bearer token; roles come from a startup string | `api/principals.py`, token box in `static/index.html` |
| L4 | The bank is a simulator reached with no idempotency, retries or reconciliation | `bank_sim`, `tools` execute path |
| L5 | Evaluation is mostly self-authored scenarios; no holdout, no cost of false positives, no latency or drift view | `evaluation/`, `docs/decision-comparison.md` |
| L6 | The knowledge base is a static ingest: no document approval, versions in use, or retrieval-quality monitoring | `rag/` |
| L7 | The LLM is shown as valuable without a measured margin over the rules | `docs/demo-report.md` |
| L8 | The customer "Ask the bank" box could not be typed in | `static/index.html` `drawChat` (reproduce first, see WP2) |
| L9 | The investigator is a fixed pipeline, not an agent that chooses what to look at next | `agents/`, `orchestration/` |
| L10 | Repo hygiene: AI-attribution trailers on some commits, AI notes in the repo root | see WP0 |

## Final status (2026-10-22)

| WP | Limitation | Result |
|----|-----------|--------|
| WP0 | L10 | Done: no trailers anywhere; CI rejects new ones |
| WP1 | L1 | Done: generated `STATUS.md`, drift test, stale counts fixed |
| WP2 | L8 | Done: Ask box typing fixed, browser test |
| WP3 | L3 | Done (prototype depth): password login, sessions, lockout; no MFA or SSO yet |
| WP4 | L2 | Partly: approvals and audit durable (`--data-dir`); checkpoints, case list, bank state, sessions, outbox open |
| WP5 | L4 | Done (simulator only): retry, failure record, reconciliation |
| WP6 | L9, L7 | Closed: investigator was already agentic; model stays optional |
| WP7 | L5 | Done: holdout, cost, latency, drift (`docs/evaluation.md`); no expert labels |
| WP8 | L6 | Partly: drafts and retired docs unreachable, access review; approver registry and per-run recall open |
| WP9 | - | Open: tag v0.2.0 after merge, once WP4b and WP8b land |

## Work packages (in order)

### WP0. Repository hygiene (L10)
- **Finding:** `main` and `origin/main` carry **no** `Co-Authored-By: Claude` trailer, and the only GitHub
  contributor is the owner. Ten trailered commits survive only on the *local* branch
  `backup/feat/phase-6d-execution` (plus an unreachable commit and `refs/original` left by an earlier rewrite).
  The earlier review that said "no trailer anywhere" was wrong about that local branch.
- **Do:** delete the local backup branch and `refs/original/*`, expire the reflog, `git gc --prune=now`;
  add `.gitattributes`/PR template and a CI grep that fails a PR whose commits contain `Co-Authored-By:`
  from a non-owner. Keep `AGENTS.md` (it is the project's guardrail file, not an author).
- **Not done:** rewriting published history (nothing to remove there).
- **Done when:** `git log --all | grep -ci "co-authored-by"` prints 0 in a fresh clone and in the local repo.

### WP1. One authoritative status page (L1)
- **Do:** generate `docs/STATUS.md` from facts, not prose: test count (`pytest --collect-only`), phase
  table (from `graph.json`), latest eval run (from `data/lab_results`), release tag. `STATE.md` shrinks to
  "read STATUS.md". A test fails if a number in the README disagrees with the generated file.
- **Done when:** one command regenerates it; the drift test passes.

### WP2. Fix the customer "Ask the bank" box (L8)
- **Do:** reproduce with the headless-Chrome tooling we already have (`scripts/make_demo_video.py` stack),
  find the cause (suspects: a re-render replacing the input mid-typing, a lingering feed timer after tab
  change, focus lost on `replaceChildren`), fix at the root, and add a browser test that types a question as
  the customer and asserts a cited passage or the "nothing you are cleared to see" message.
- **Also:** show the customer-channel filter result clearly (which sections were withheld, never their text).
- **Done when:** the browser test passes for customer and employee tokens.

### WP3. Real sign-in instead of pasted tokens (L3)
- **Do:** a username/password login with a short-lived signed session (HttpOnly cookie, expiry, logout),
  users and roles in a store, passwords hashed (argon2/scrypt), per-IP login rate limit, role-based checks
  unchanged (still plain code, never an LLM). A second factor via TOTP for employee roles. The login page
  replaces the token box; bearer tokens stay for scripts and tests.
- **Not done:** real OIDC/SSO. The auth module sits behind a `Authenticator` protocol so an OIDC provider
  (Keycloak, Entra) is a drop-in; we document the mapping of IdP groups to `Role`.
- **Done when:** tests cover wrong password, expiry, lockout, role escalation attempts, cookie flags.

### WP4. Durable state (L2)
- **Do:** SQLite (via SQLAlchemy-free `sqlite3`, WAL) behind the existing store protocols for cases,
  approvals and the checkpoint saver; audit log written append-only with its hash chain, verified on start;
  a transactional **outbox** table for events (case opened, action executed). Restart test: open a case,
  kill the process, resume, approve, execute.
- **Not done:** Postgres, a broker. The protocols make that a new adapter, and ADR 0011 records the choice.
- **Done when:** restart/resume tests pass and tampering with a DB row is detected on verify.
- **Status (4a):** approvals (with single-use consumption) are durable in SQLite and the audit chain is durable and re-verified on open, both switched on by `--data-dir`. **Still open (4b):** case checkpoints and the case list (needs `langgraph-checkpoint-sqlite`), the simulated bank's state, sessions, and the outbox.

### WP5. Bank adapter boundary (L4)
- **Do:** an `execute(action, idempotency_key)` contract on the tool layer; replays return the first result;
  bounded retry with backoff on transient errors; a **reconciliation** job comparing audit "executed" events
  with bank state and reporting mismatches; a ticket/handoff record for human-operations follow-up.
- **Not done:** any real bank connection. The simulator stays the only backend.
- **Done when:** tests for duplicate submit, timeout-then-retry, and a deliberately injected mismatch.

### WP6. Make the investigator genuinely agentic (L9, L7)
- **Review result: premise was wrong.** `agents/investigator_agent.py` already is a bounded tool-use loop (the model picks lookups, 6-step limit, third-party text removed, claims fact-checked by `agentic_analysis`). No rebuild needed; L9 is closed as a mis-diagnosis. L7 (is the model worth it?) is answered by the measured comparison in `docs/demo-report.md`, and the model stays optional.
- **Do:** replace the fixed order with a bounded tool-use loop: the model picks the next read-only tool call
  from the closed tool list, has a step and token budget, every observation is fenced with `wrap_untrusted`,
  the final output must still be typed findings that a deterministic fact-checker confirms. The model never
  acts, never picks the channel, never authorises. Fixed-pipeline stays as fallback and baseline.
- **Done when:** scripted-provider tests (loop limits, hostile tool output, refusal) and a Claude run showing
  confirmed/added/dropped counts against the baseline.

### WP7. Independent evaluation (L5, L7)
- **Status: done** via `scripts/run_holdout_eval.py` and `docs/evaluation.md` (holdout seeds, assumed cost matrix, latency, drift, red-team pointers). Expert labels remain unavailable.
- **Do:** a holdout scenario set generated from a different seed family and never used for tuning; cost
  matrix (false-positive restriction vs missed fraud, in assumed currency units, stated as assumptions);
  latency and token cost per case; a drift check comparing indicator frequencies across runs; a red-team
  suite (prompt injection in memo text, channel spoofing, approval replay).
- **Not done:** expert-labelled data: we have none; the report says so.
- **Done when:** `docs/evaluation.md` reports holdout vs tuning numbers with the caveats above.

### WP8. RAG lifecycle (L6)
- **Do:** a document registry with status (`draft/approved/retired`), approver and version; only `approved`
  is retrievable; every answer records which versions were used; a retrieval test set with recall@k tracked
  per run; an access-review report of which role can see which section.
- **Done when:** retrieving a `draft` or `retired` doc is impossible (test first), and the quality report runs.
- **Status (8a):** drafts and retired documents are now unreachable even with history requested (this was a real gap), and `access_review()` reports visibility per clearance. **Open (8b):** approver and version registry, recall@k tracked per run.

### WP9. Final pass
- Regenerate STATUS, re-run the full evaluation with Claude, update README, graph, log, tag `v0.2.0`.

## How we work each WP
Branch `feat/wpN-...` -> tests first for safety parts -> code -> `ruff`, `mypy`, `pytest` -> update
`graph.json`, `PROJECT_LOG.md`, STATUS -> conventional commits, small and frequent -> PR with `Closes #N`.
Live tests use the Claude API through the existing gateway; keys stay in `.env`.
Commits carry no AI attribution trailer.
