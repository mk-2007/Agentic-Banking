# ADR 0013: Every action in the closed set is carried out by a guarded tool

- Status: accepted
- Date: 2026-10-18

## Context
Running every scenario through the service showed two gaps. Only `block_card` and `freeze_account` ever ran;
the other five actions were recommendations that stopped at `decision_ready`. And an approved
`request_customer_verification` case went to the execution tool, which supports only block and freeze, so a
human approved a correct recommendation and the case ended `failed_tool`. No test approved a Level 3
verification case end to end, so nothing caught it. Separately, the approval rule only runs when a vote arrives,
so a case nobody voted on never timed out, and a `modify` verdict returned the case to `decision_ready` with
nothing to continue it.

## Decision
1. A second tool, `perform_case_action`, carries out the rest of the closed set. It queues a follow-up on the
   bank's operations desk (`bank_sim` outbox: watch, KYC request, verification request, analyst ticket). It is
   callable only by the execution service (deny by default, in the permission matrix) and cannot block a card or
   freeze an account.
2. Level 1-2 actions run on their own: the case goes `decision_ready -> approved` **by policy** (an audit note
   says so), through the same tool, effect check and completion as any other action. Level 3
   `request_customer_verification` still needs a valid, single-use approval, checked by the same helper
   (`consume_approval`) the freeze path uses.
3. `modify` ends in `escalated`: a reviewer who wants the action changed hands the case to an analyst and
   nothing runs.
4. `CaseService` times out a pending case once its approval has expired, by resuming it with no votes so the
   pure `evaluate_approval` rule makes the call.

## Consequences
- Good: every action the system can recommend, it can also perform, and each is bounded by the same approval and
  audit rules. The Level 3 gap is closed and a test approves every Level 3 and 4 path.
- Cost: follow-ups are written to a simulated outbox, not sent anywhere. A low-risk case now finishes at
  `completed`, not `decision_ready`, so anything reading that status changed with it.
- The authorization model is unchanged: no action runs without the checks it needed before.
