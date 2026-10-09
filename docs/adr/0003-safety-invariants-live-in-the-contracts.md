# ADR 0003: Safety invariants are enforced by the domain contracts

- Status: accepted
- Date: 2026-10-09

## Context
Decision providers (rule scorer, LLM, possibly JEV later) are interchangeable, and LLM output is
untrusted. If safety rules lived only inside one provider, replacing it could silently remove them.

## Decision
Encode the safety rules (cautious action under uncertain evidence, risk/approval consistency,
evidence and policy required for Level 3+, Level 4 needs two approver roles, audit hash chain) as
validators on the domain models. Higher layers add their own gates, but the contracts are the last line of defence.

## Consequences
- Good: any provider's output is checked identically; unsafe objects cannot exist, so they cannot be stored or executed.
- Good: rules are unit-tested in one place, with no model involved.
- Cost: changing a rule means changing the domain contract and its tests, which is intended friction.
