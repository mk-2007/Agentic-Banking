# Case orchestration (Phase 6a)

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

## Not built yet (by design, and on the tracker)

| Gap | Where it lands |
|---|---|
| Human approval pause and resume | 6b |
| Loop limits, retries, timeouts, and loop-back when records are missing | 6c |
| Audit event for every status change (the in-memory `trail` is the stand-in) | 6c |
| The decision itself (ranked actions, policy citations) | Phase 7, behind `decision_ready` |
| A durable checkpoint store (only an in-memory saver is tested) | 6b |

## Honest limits

- The sequence is fixed. There is no model planner or supervisor choosing steps; with seven scenarios and
  four agents a fixed order is simpler and testable, but it will not adapt to a case that needs a different
  path.
- When verification reports missing records the case stops in `failed_validation` instead of looping back to
  gather them again. Looping safely needs the limits from 6c.
- A tool problem ends the run at once; there is no retry yet.
- Checkpoint behaviour is proven with LangGraph's in-memory saver only. A database-backed saver may
  serialize slightly differently; 6b will test the one we choose.
- Dependency: `langgraph>=1.2,<2`. The allowlist API (`allowed_msgpack_modules`) is recent; if a LangGraph
  update changes it, the checkpoint tests fail loudly rather than silently loosening the check.
