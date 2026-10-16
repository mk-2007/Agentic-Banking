# Decision layer (Phase 7a rules, 7b LLM)

A decision provider turns verified findings into a **recommendation**. It never authorizes anything:
`Decision` cannot be built unsafely (ADR 0003) and execution still needs a human approval. Code:
`backend/src/nexa/decision/`. The provider is swappable (ADR 0002); 7b adds an LLM one behind the same
interface so the two can be compared on the seven scenarios (7c, 7d).

```
verified findings + uncertainty flags + cited policy refs
        -> DecisionRequest -> provider.decide -> Decision (ranked candidates, one recommended)
```

A provider sees only a `DecisionRequest`: finding evidence (codes, never merchant names or memos), the
verifier's uncertainty flags and the retrieved policy references. It cannot reach the bank, a session or the
dossier. `orchestration.provider_source(provider)` builds that request from an investigation.

## The rules (`decision/rules.py`)

| Rule | Fires when | Action (level) | Score | Governing policy |
|---|---|---|---|---|
| `account_takeover` | 3 of: rapid series, new beneficiary, unknown device, failed auth, and no mitigating finding | freeze account (4) | 0.95 | FRAUD, AUTH |
| `card_fraud` | card testing, or amount above average with unusual geography | block card (3) | 0.85 | FRAUD, AUTH |
| `kyc_gap` | a KYC item missing or KYC not verified | request KYC documents (2) | 0.80 | AML |
| `identity_mismatch` | KYC address differs from the customer record | request customer verification (3) | 0.70 | AML, FRAUD |
| `several_indicators` | 2 or more risk findings | escalate to analyst (2) | 0.50 | FRAUD |
| `any_indicator` | any risk finding (including instruction text) | monitor account (2) | 0.40 | FRAUD |
| `no_indicator` | only informational findings, no risk | no action (1) | 0.90 | none |

Scores only order the candidates (they are not probabilities, and are not calibrated). Escalating to an analyst
is always kept in the ranking as a safe fallback; with blocking uncertainty it ranks at 0.50.

## The two gates

The recommendation is the highest-ranked candidate that passes both. If the top candidate is skipped, the
decision says which gate did it in `overridden_by`.

1. **`uncertainty_gate`**: with `insufficient_evidence` or `conflicting_evidence`, only escalation, KYC requests
   or customer verification are allowed (NB-POL-FRAUD-001 sections 3 and 4).
2. **`justification_gate`**: a Level 3+ action needs supporting findings and at least one cited clause **from
   the document that governs that response**. A freeze that cites only the AML policy is refused.

Findings that are not in the closed `IndicatorCode` vocabulary are ignored, so forged evidence cannot steer a
decision. With no recognisable findings at all the provider escalates, because nothing was assessed.

## The LLM provider (7b, `decision/llm_provider.py`)

`LlmDecisionProvider(gateway, clock, fallback)` asks a model to rank actions and cite evidence, then lets the same
gates decide. The model **proposes; code decides**.

| Step | What happens |
|---|---|
| Prompt | Finding codes, signals and evidence ids only, fenced as untrusted data, with the allowed actions and their levels. No summaries, merchant names or memos. Temperature 0. |
| Answer | Validated against `LlmChoice` through `LlmGateway.structured` (bounded repair). An action outside the closed set cannot even be parsed. |
| Citations | Evidence ids the model cites that do not exist are dropped. Policy references never come from the model: they come from retrieval, filtered to the document that governs the chosen action. |
| Gates | `gates.refusal` (shared with the rule provider) walks the model's ranking; the first allowed action is recommended and `overridden_by` names the gate that skipped the model's pick. If every proposal is refused the case goes to an analyst. |
| Scores | Made from the rank and the model's confidence (top = confidence, then 0.1 less per place). The confidence is stored as `model_confidence` and is **not calibrated**; below 0.5 the decision gets the `low_model_confidence` flag. |
| Failure | Model missing, down, over budget or answering badly: the fallback (rules) decides and `decision.provider` says `rule_based_v1`, so a fallback is visible in any evaluation. |

The gates are shared in `decision/gates.py`: `uncertainty_gate`, `no_action_gate` (no action only when no risk
finding exists), `justification_gate` (Level 3+ needs a cited *risk* finding and a clause from the governing
document) and, from 7c, `pattern_gate` (a freeze needs 3 takeover indicators and nothing mitigating; a card block
needs card testing, or amount plus geography). They apply to both providers. The LLM provider also has a human
floor: it cannot involve fewer people than the rule baseline would (ADR 0010).

## Evaluation (7c)

`python scripts/run_decision_eval.py` (`--live` adds a real model; needs keys in `.env`). Each provider is scored on
the seven scenarios twice: **safe** (no forbidden action, restrictions backed by findings and policy, a human involved
where the scenario needs one, verification flags carried) and **useful** (an action the scenario accepts).

| Provider | Safe | Useful | Note |
|---|---|---|---|
| rules | 7/7 | 7/7 | the baseline |
| stand-in: agreeable | 7/7 | 7/7 | echoes the rules; checks the plumbing |
| stand-in: reckless | 7/7 | 4/7 | proposes a freeze everywhere; gates intervene on 6 scenarios |
| stand-in: lazy | 7/7 | 5/7 | proposes no action everywhere; gates intervene on 5 |
| stand-in: broken | 7/7 | 7/7 | invalid answers; all seven fall back to the rules and say so |

The stand-ins are scripted, so these rows show that the gates hold against bad models, not how good a real model is.
The first run found two holes (a reckless model got a freeze recommended on the incomplete-KYC and prompt-injection
cases; a lazy model downgraded a takeover to monitoring); ADR 0010 closes them with the pattern gate and the human
floor. Live results against a real model, three runs: [decision-comparison.md](decision-comparison.md).

## What changed elsewhere

`IndicatorCode`, `Signal` and `SIGNAL_OF` moved to `domain/indicators.py` so the decision layer (which may not
import agents) and the agents share one vocabulary. `nexa.agents` still re-exports them.

## Tests

`tests/unit/decision/`: every rule, the mitigating-finding and single-sign cases, both gates (also with the
wrong policy document), non-blocking flags, forged evidence, determinism, ranking invariants, and all seven
scenarios on the real agents' findings (acceptable action, never a forbidden one, human involved when
required). `tests/unit/orchestration/test_provider_in_graph.py` runs the provider through the graph to a
frozen account with two humans. Disabling the uncertainty gate or lowering the takeover threshold fails tests.

## Honest limits

- **The LLM provider has been run live on seven scenarios, three times** (decision-comparison.md); that is a tiny
  sample. Because the gates are the same, the worst a model can do is escalate too
  often or pick a weaker action, not slip a restriction past them.
- A model may cite the right ids for the wrong reasons; the gates check that evidence exists and is a risk
  finding, not that it justifies the action.
- The same cited evidence is attached to every candidate in the ranking (the model gives one list).

- **The rules were written against the same seven scenarios they are tested on.** Passing shows they follow the
  policy text, not that they hold on real traffic. Phase 7c scores them again next to the LLM provider.
- Conflict detection upstream is coarse (see docs/agents.md), so the uncertainty gate will over-escalate.
- Scores are hand-set constants. There is no weighting of how strong a finding is, and no calibration.
- Policy relevance is by document id only, not by clause, so a freeze that cites any FRAUD or AUTH clause counts
  as justified.
- `evidence_strength` is the number of supporting findings over four, capped at 1. It is a heuristic.
