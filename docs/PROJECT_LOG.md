# Project log

Newest first. Add an entry whenever a step is finished or a decision is made.

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
