# Domain contracts (Phase 1)

All contracts live in `backend/src/nexa/domain/`. They are immutable Pydantic models that reject
unknown fields, and every safety rule below is enforced by a validator, so an invalid object cannot exist.

| Module | What it defines | Key rules enforced |
|---|---|---|
| `actions` | `ActionType` (closed set of 7), `RiskLevel` 1-4 | Every action has a risk level; only `freeze_account` is Level 4 |
| `actors` | `Role`, `Actor` | Users hold human roles, agents hold agent roles, the system has none |
| `evidence` | `Evidence`, `SourceRef`, `PolicyRef` | Every fact names a tool record or a versioned policy clause |
| `case` | `Case`, `CaseStatus`, transitions | Only listed transitions are legal; terminal states are final |
| `decision` | `Decision`, `CandidateScore` | See below |
| `approval` | `ApprovalRequest`, `ApprovalVote`, `evaluate_approval` | Level 4 needs two different approver roles; expired or late votes never approve |
| `tooling` | `ToolSpec`, `ToolCall`, `ToolResult` | Snake-case names; state-changing tools are at least Level 2 |
| `audit` | `AuditEvent`, `seal`, `first_broken_link` | SHA-256 hash chain; editing, removing or reordering events is detected |

## Decision invariants

A `Decision` is a recommendation, never an authorization. It cannot be constructed if:

1. candidates are unsorted or repeated, or the recommendation is not among them;
2. the recommendation is not the top-ranked candidate and no hard gate (`overridden_by`) is named;
3. evidence is insufficient or conflicting and the action is anything other than escalate / request information;
4. `risk_level` or `approval_required` disagree with the recommended action;
5. a Level 3+ action lacks supporting evidence or a cited policy;
6. the same evidence both supports and opposes a candidate.

## Case lifecycle

```
CREATED -> PLANNING -> EXECUTING <-> WAITING_FOR_TOOL
                          |
                      VERIFYING -> DECISION_READY -> WAITING_FOR_APPROVAL -> APPROVED
                                          |                                     |
                                     (auto, Level 1-2) -----------------------> EXECUTED -> VERIFIED -> COMPLETED
Failure/end states: FAILED_TOOL, FAILED_VALIDATION, BLOCKED_BY_POLICY, REJECTED_BY_HUMAN, ESCALATED, TIMED_OUT
```

Naming note: the Level 3 and 4 actions are `block_card` and `freeze_account` (the action itself), not
"recommend_...". The decision *recommends* it, a human *authorizes* it, and only then is it executed.
