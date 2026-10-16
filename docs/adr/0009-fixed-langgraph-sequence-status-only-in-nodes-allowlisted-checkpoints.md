# ADR 0009: A fixed LangGraph sequence; status changes only in nodes; allowlisted checkpoints

- Status: accepted
- Date: 2026-10-14

## Context
The PRD calls for a LangGraph state machine that coordinates the agents and pauses for human approval.
Pausing means saving a case and restoring it later, which raises two problems: the saved data must come
back with its types intact, and rebuilding arbitrary types from stored data is unsafe. We also need
failures to be visible states rather than exceptions.

## Decision
1. The graph is a fixed sequence: open, gather, analyze, research, verify, then ready or failed. No model
   plans or reorders steps.
2. A case's status changes only inside the graph's nodes, only via `Case.transition_to`. Agents never see
   or set it.
3. Tool problems and blocking verification issues are terminal states (`failed_tool`,
   `failed_validation`) recorded with a short code; the run ends cleanly.
4. Graph state holds only contracts, enums and lists. Anything stored in a checkpoint must be on an
   explicit allowlist of our own types (`checkpoint.py`), and a test fails if a new state type is missing.
5. Agents are passed in through `AgentSet`, so tests can substitute failing stand-ins.

## Consequences
- Good: every run's path is checkable (`trail`), illegal jumps are impossible, a saved case restores exactly,
  and a tampered checkpoint cannot instantiate arbitrary classes.
- Cost: adding a state field means listing its type; a fixed order cannot adapt to unusual cases; contracts
  replace some dataclasses (`PolicyResult`).
- Follow-ups: approval pause (6b); limits, retries, audit events per transition (6c).
