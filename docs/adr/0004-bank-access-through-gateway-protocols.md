# ADR 0004: Bank access goes through gateway Protocols; data is deterministic

- Status: accepted
- Date: 2026-10-10

## Context
The prototype has no real bank data, but the design must scale to a real banking system. Tests, demos
and evaluation also need identical data on every run and every machine.

## Decision
1. `bank_sim/gateway.py` defines `Protocol` interfaces (customer, account, transaction, KYC, account actions).
   The tool layer depends on these, never on `InMemoryBank`.
2. Read APIs and state-changing `AccountActionAPI` are separate interfaces, so tools can grant read access broadly
   and wrap the state-changing one in approval checks.
3. Synthetic data comes from a generator with its own pseudo-random generator (not the `random` module),
   is committed, and a test regenerates it to prove it matches.
4. Amounts are whole PKR integers; evaluation scenarios are data (`scenarios.json`), not code.

## Consequences
- Good: a real gateway can replace the simulator without changing tools, agents or orchestration.
- Good: results are reproducible; scenarios double as the evaluation set.
- Cost: the generator is extra code to maintain; regenerating data means committing the new files.
