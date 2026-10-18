# ADR 0016: Evaluate on randomised, labelled traffic, with and without a model

- Status: accepted
- Date: 2026-10-18

## Context
Every earlier evaluation used cases we wrote by hand around the system's own thresholds. Passing them shows the rules
follow the policy; it cannot show how the system behaves on traffic we did not shape. It also hid something: some
outcomes were right by accident (structuring escalates only because the rules escalate when they recognise nothing).

## Decision
1. A **persona** generator (`evaluation/simulator.py`) produces a different payment sequence for every seed, scaled to the
   account's own habits: three honest personas (routine shopping, one large ordinary purchase, a transfer to a new payee)
   and four fraudulent ones (account takeover, card testing, structuring, a new phone). The table of labels was written
   before the first run and is not changed to fit a result.
2. A runner (`api/sim.py`) gives each episode a **fresh simulated bank, case service and monitor**, posts the payments the
   way the customer app does (cash deposits go straight to the bank), lets the monitor open cases, and judges the
   recommendations against the label.
3. The score separates **caught** (a case opened and handled acceptably), **recognised** (a case held the persona's
   defining finding: right answer for the right reason) and **safe** (no over-restriction). Honest customers are judged on
   harm (restricted or contacted) and on how often a case was opened on them.
4. The same seeds run **without a model** (the baseline) and, with `--llm`, **with a model** in the monitor and the
   investigator, so the two compare on identical traffic. The result is saved to `data/lab_results/sim.json`; the server only
   reads it (as for the live-model lab), so no request waits on a model.

## Consequences
- Good: a measure that is not tuned to our thresholds, a baseline that exposes right-for-the-wrong-reason answers, and a
  place where the model can be shown to add something (structuring is caught by accident without it and recognised with it).
- Cost and limits: the personas are our idea of fraud and the labels our reading of the policy; a few episodes is a few
  episodes; free-tier model runs are slow and sometimes rate-limited, which the report shows as `model_unavailable`.
