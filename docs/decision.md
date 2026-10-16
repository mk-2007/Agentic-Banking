# Decision layer (Phase 7a: rule-based provider)

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

- **The rules were written against the same seven scenarios they are tested on.** Passing shows they follow the
  policy text, not that they hold on real traffic. Phase 7c scores them again next to the LLM provider.
- Conflict detection upstream is coarse (see docs/agents.md), so the uncertainty gate will over-escalate.
- Scores are hand-set constants. There is no weighting of how strong a finding is, and no calibration.
- Policy relevance is by document id only, not by clause, so a freeze that cites any FRAUD or AUTH clause counts
  as justified.
- `evidence_strength` is the number of supporting findings over four, capped at 1. It is a heuristic.
