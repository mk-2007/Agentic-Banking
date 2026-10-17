# Specialist agents (Phase 5b)

Four agents, one job each, all reaching the bank **only through tools**. They hand each other typed
evidence, never free text. Code: `backend/src/nexa/agents/`. Evaluation: `python scripts/run_agent_eval.py`.

```
alert -> Case -> DataAgent -> Dossier (typed facts + evidence)
                    |
                    v
              AnalysisAgent -> findings (closed set of codes, recomputable)
                    |
                    v
              PolicyAgent -> cited clauses with versions (+ topics with no policy backing)
                    |
                    v
           VerificationAgent -> passed / issues / uncertainty flags  -> (Phase 7) decision
```

| Agent | Role (permission matrix) | Tools it may call | Uses a model? |
|---|---|---|---|
| Data | `data_agent` | transaction details, customer profile, account details, KYC status | No |
| Analysis | `analysis_agent` | transaction history | No |
| Policy | `policy_agent` | `search_knowledge_base` | Optional: narrows clauses |
| Verification | none needed | none (re-derives from evidence) | No |

`ToolSession` sends every call through `ToolRegistry.invoke` as the agent's own actor and case, so role
checks, case scoping and audit are the tool layer's, not the agent's. `AgentContext.channel` has **no
default**: trusted code must say whether the session is for employees or customers.

## Why most of it is plain code

Thresholds are policy (NB-POL-FRAUD-001, NB-POL-AML-001), mirrored in `FraudThresholds`, and a test keeps
the documents and the numbers identical. A model cannot be asked to count to five reliably or to give the
same answer twice. So the analysis is arithmetic over the customer's own earlier history, the baseline
excludes the suspicious burst itself (a burst cannot make itself look normal), and every finding stores
the numbers it was computed from.

## Findings are a closed vocabulary

`IndicatorCode` has 18 values (`amount_above_average`, `card_testing`, `unknown_device`, `kyc_item_missing`,
...), each with a signal: `risk`, `mitigating` or `info`. A finding is an `Evidence` object whose `data`
holds `code`, `signal` and `derived_from` (the evidence ids it rests on). Nothing a model or a merchant
wrote can enter a finding, because there is no free-text field to put it in.

## Verification re-checks, it does not trust

For each finding the verification agent confirms: the evidence it cites exists; the signal matches the
code; and the threshold still holds when recomputed from the recorded numbers. A forged or stale finding
is rejected (`unsupported_finding`). It also sets the flags a `Decision` must respect:

- `insufficient_evidence`: fewer than 10 transactions in 90 days, or a required record is missing;
- `conflicting_evidence`: risk findings and mitigating findings (travel notice, trusted device, familiar
  merchant) at once, which NB-POL-FRAUD-001 section 4 says must not be forced into a conclusion.

Missing policy support for risk findings is reported but does not block: the decision layer decides
whether a Level 3+ action can be justified (a `Decision` cannot be built without a cited policy).

## The one model step, and its guard rails

The policy agent chooses topics from the finding codes and retrieves clauses by tool. A model may then
narrow them to the ones that apply. It can only pick refs the tool returned (invented refs are dropped
and counted), clause text is sent fenced as untrusted data, and if the model is missing, down, over
budget or picks nothing valid, every retrieved clause is kept. Third-party text (merchant names, memos)
is never sent to a model at all. The evaluation checks that such text is absent from evidence in every scenario, and that the injection scenario's merchant and memo text is absent from every prompt.

A topic counts as covered only if the **policy that governs it** was retrieved, because search always
returns its best guesses and "found something" would prove nothing. A customer-channel session therefore
reports gaps for restricted policy instead of quietly using weaker material.

## Evaluation

`data/agent_eval/expectations.json` states, per scenario, which findings must surface, which risk codes
are allowed, the exact uncertainty flags, and which policies must be cited. `python scripts/run_agent_eval.py`
runs all eleven (`--live` lets a real model do the narrowing). Each scenario gets up to 12 checks, including: verification
passes; required findings from `scenarios.json` surface (each sentence is mapped to a code, and an
unmapped sentence fails); no unexpected risk findings; flags match; policies cited; no governing policy
missing; third-party text absent from evidence and prompts; agents never triggered a denied tool call;
and, for scenario E, the unauthorized freeze is refused and the account stays active.

Scenario results (deterministic run): 11 of 11 pass. I mutation-tested the harness (asking for a finding
that should not exist, a wrong flag, an empty allow-list) and each correctly failed.

## Honest limits

- **Scenario data is small and ours.** The thresholds fit the first seven synthetic scenarios (G to J were added later); passing them
  shows the rules do what the policy says, not that they would hold on real traffic.
- **`instruction_text` is a heuristic.** Seven regular expressions catch obvious attempts ("ignore all
  previous instructions", "system notice to AI agents", "freeze the account"). A paraphrased or
  non-English attempt will slip through the detector. The real defence is structural: such text is never
  placed in evidence or in a prompt, so it has nothing to act on.
- **Conflict detection is coarse.** Any risk finding plus any mitigating finding means "conflicting". A
  familiar merchant alone can trigger it next to a large amount. That is conservative (it forces an
  analyst) and matches the policy wording, but it will over-escalate on real data.
- **"New beneficiary" counts payments**, because the bank flags each payment, not each beneficiary. Six
  payments to one new account read as "6 payment(s)", not six beneficiaries.
- **The model step has not been run against a live provider by this suite.** It is tested with a scripted
  provider. `--live` exists for that; Gemini was overloaded when last tried (see docs/llm-gateway.md).
- **A straight-line `investigate()` is not the orchestrator.** Planning, loop limits, retries, the
  failure states and the human approval pause arrive in Phase 6. Tool failures raise `AgentToolError`
  for orchestration to map onto `FAILED_TOOL`.
- Findings carry no weights and scores are not probabilities. Ranking actions is Phase 7.
