# ADR 0012: Capability evidence: baselines, hostile models, a hard tier and a live model

- Status: accepted
- Date: 2026-10-17

## Context
The first lab run passed every case. That is expected on cases built around the thresholds, and it proves
consistency, not capability. It also hid a weakness in the scoring: labels accept several actions and
"escalate to an analyst" is acceptable almost everywhere, so a system (or a rule) that escalates everything
scores well.

## Decision
1. Scoring gains two stricter measures. **Preferred**: the action the label lists first. **Over-escalated**:
   escalated where the label needed no human. A shared `judge` function applies the same checks to the
   agents, to baselines and to hostile models.
2. **Baselines.** Five simple rules (never act, always escalate, big amount, unusual amount, multi-signal risk
   score) are scored on the same cases with the same checks. None cites a finding or a policy, so a restriction
   from a rule counts as unjustified. The agents' thresholds were tuned on the original scenarios and the
   rules were not tuned at all; the UI says so.
3. **Hostile models.** Scripted stand-ins (agreeable, reckless, lazy, broken) sit behind the real
   `LlmDecisionProvider`. We report proposals that would have been unsafe if accepted and the unsafe
   recommendations that actually came out. A test fails if any comes out.
4. **Hard tier.** Sixteen realistic stories written without tuning the thresholds to them, some deliberately
   blind spots. Labels were fixed before the first run and are not changed afterwards.
5. **Live model.** `scripts/run_lab_live.py` runs a real model behind the same gates and saves
   `data/lab_results/live.json`. The server never holds an API key and never calls a model; it only reads the saved
   file.
6. Layer rule: `evaluation` may now import `decision` and `llm` (to run stand-in and live models behind the
   real provider). It still never writes to the bank.

## Consequences
- Good: the headline claim becomes testable and shows its limits: how often the agents choose the preferred
  action, how much they over-escalate, and that no hostile model gets an unsafe result through.
- Cost: the preferred action is the first-listed one, an ordering written before these measures existed, so it is
  a convention and not a gold standard. The hard tier is small and ours. A live run is slow on a free tier.
