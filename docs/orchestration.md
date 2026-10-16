# Case orchestration (Phase 6a, 6b, 6c)

A LangGraph graph that carries one case through the four agents and ends in a clear status. Code:
`backend/src/nexa/orchestration/`. Try it: `python scripts/run_case.py --all`.

```
open_case -> gather -> analyze -> research -> verify -> mark_ready        decision_ready
                |         |          |            \-> fail_validation    failed_validation
                +---------+----------+--> a tool problem ends the run    failed_tool
```

| Step | Agent | Case status after |
|---|---|---|
| `open_case` | none | created -> planning -> executing |
| `gather` | data | executing |
| `analyze` | analysis | executing |
| `research` | policy | executing |
| `verify` | verification | verifying (and every evidence id recorded on the case) |
| `mark_ready` | none | decision_ready |
| `fail_validation` | none | failed_validation (blocking issue; code says which) |
| any step, tool problem | none | waiting_for_tool -> failed_tool (code says which tool and why) |

## Rules this graph keeps

- **Status changes only in `nodes.py`, only through `Case.transition_to`**, which rejects any move the
  state machine forbids. Agents never see the status and nothing a model says can change it. A test
  proves a step cannot skip a status.
- **Failures are states, not crashes.** A refused tool, a timeout or inconsistent records end the run in
  `failed_tool`; a forged or unsupported finding ends it in `failed_validation`. The run records a short
  code (`get_transaction_history:timeout`), never free text from a tool.
- **Non-blocking verification issues do not stop a case.** Missing policy support, for example, is shown
  on the result and left for the decision stage to weigh.
- **State is contracts and lists only.** Checkpointing turns bare tuples and dataclasses into lists and
  dicts; contracts are re-validated on the way back. `PolicyResult` became a contract for this reason.
- **A checkpoint may only rebuild types we list.** `checkpoint.py` names every type a case can contain.
  LangGraph warns that rebuilding unlisted types will be blocked in a future version, and rebuilding
  arbitrary types from stored data is a code-execution risk anyway. A test runs a whole case through a
  checkpointer and fails on any refusal, so a new state field without a listed type is caught.
- **Agents are injectable.** `AgentSet` lets tests swap in a stand-in that fails in one chosen way.

## Human approval pause (6b)

Pass a decision source to `build_case_graph(ctx, checkpointer=..., decide=...)` and the graph continues past
`decision_ready`:

```
mark_ready -> propose -> request_approval -> await_votes (pauses) -> settle
                |                                  ^                   |
                +-> blocked_by_policy              +--- still pending -+
```

| Step | What happens |
|---|---|
| `propose` | The source returns a `Decision`. One for another case, or one that drops a blocking uncertainty flag verification found, ends in `blocked_by_policy` (`decision:wrong_case`, `decision:ignored_uncertainty`). |
| `request_approval` | Level 3+ only. Orchestration code builds the `ApprovalRequest` from the approval matrix (roles, expiry) and the case's own account; the status becomes `waiting_for_approval`. Level 1-2 stops at `decision_ready`. |
| `await_votes` | Saves the run and pauses (`interrupt`). `resume_case(graph, thread_id, votes)` continues it. |
| `settle` | The pure `evaluate_approval` rule decides: approved, rejected (`rejected_by_human`), escalated, expired (`timed_out`), modify (back to `decision_ready`), or still pending (pause again). Votes accumulate across resumes. |

Execution of an approved action is not part of this graph yet; the run ends at `approved` and the request
id is what the guarded execution tool needs.

## Limits, retries and audit (6c)

`build_case_graph(..., audit=AuditRecorder(...), limits=RunLimits(...))`.

| Bound | Default | What happens at the limit |
|---|---|---|
| `max_attempts` per agent step | 2 | A tool error in `TRANSIENT_TOOL_CODES` (`timeout`, `internal_error`) moves the case `executing -> waiting_for_tool -> executing` and the step runs again; at the limit the case ends `failed_tool` with the code. Refusals (denied, out of scope, invalid arguments) are never retried. |
| `max_vote_rounds` | 5 | A case still pending after this many resumes ends `escalated` with `approval:too_many_rounds`. |

Audit events are written by the orchestrator (a `system` actor) and never by an agent: `case_created`, one
`state_changed` per transition (`executing->verifying`), `decision_made`, `approval_requested`, one
`approval_vote_cast` per vote (with the approver id) and an `error` carrying the failure code. Details are
statuses, ids and codes only, never third-party text. Without a recorder nothing is written and behaviour is
otherwise identical.

## Not built yet (by design, and on the tracker)

| Gap | Where it lands |
|---|---|
| Loop-back to gather again when records are missing, and wall-clock timeouts per step | not planned; the limits exist, nothing loops back yet |
| The decision itself (ranked actions, policy citations) | Phase 7, behind `decision_ready` |
| A durable checkpoint store (only an in-memory saver is tested) | 8a (API) |
| Executing the approved action and verifying it | 6d |

## Honest limits

- The sequence is fixed. There is no model planner or supervisor choosing steps; with seven scenarios and
  four agents a fixed order is simpler and testable, but it will not adapt to a case that needs a different
  path.
- When verification reports missing records the case stops in `failed_validation` instead of looping back to
  gather them again. Looping safely needs the limits from 6c.
- Retries are immediate (no backoff) and only for two error codes; a real transient failure may need a pause between tries.
- Audit events are written as the graph runs. A crash between a transition and its event, or a step LangGraph replays on resume, can leave a missing or duplicate event; the chain stays valid either way.
- Checkpoint behaviour is proven with LangGraph's in-memory saver only (including resuming from a freshly
  built graph). A database-backed saver may serialize slightly differently.
- The graph trusts that votes it is resumed with come from authenticated approvers; it checks roles,
  request id and time window, not identity. Authenticating who voted belongs to the API (8a).
- There is no reminder or escalation timer: expiry is noticed only when someone resumes the case.
- Dependency: `langgraph>=1.2,<2`. The allowlist API (`allowed_msgpack_modules`) is recent; if a LangGraph
  update changes it, the checkpoint tests fail loudly rather than silently loosening the check.
