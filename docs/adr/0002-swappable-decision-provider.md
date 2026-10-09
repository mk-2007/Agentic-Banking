# ADR 0002: Decision layer behind a swappable provider interface

- Status: accepted
- Date: 2026-10-09

## Context
The decision step must be precise, cheap and auditable. TypeSafe AI's JEV (a "System One" model
returning typed decisions) is a possible fit, but we have no access to it and it is a vendor
product whose published numbers are self-reported.

## Decision
Define a `DecisionProvider` interface in `decision/`. Initial implementations:
1. A deterministic **rule scorer** over structured evidence (baseline).
2. An **LLM structured-output provider** validated against the same schema.

A JEV adapter can be added later without touching other layers. Hard gates in code (insufficient or
conflicting evidence, role limits) override any provider. Provider scores are rankings with an
evidence-strength value, not calibrated probabilities, until calibrated on our own scenarios.

## Consequences
- Good: no dependency on unavailable access; demo-safe; enables a baseline-vs-provider evaluation.
- Cost: we own the rule scorer and its tests.
