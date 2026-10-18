# ADR 0014: A model investigates, and code checks what it claims

- Status: accepted
- Date: 2026-10-18
- Amends: ADR 0008 (analysis stays deterministic by default; a model may now add to it)

## Context
The analysis step was fixed arithmetic. That is safe and repeatable, but it is not an agent: nothing chose what to
look at, nothing reasoned over what it read, and a pattern the arithmetic has no rule for (structuring, scenario I)
was never found. The project's aim is agents whose work is as verifiable and justified as an analyst's.

## Decision
1. A new agent, the **investigator**, runs only when a model gateway is configured and the context opts in
   (`AgentContext.investigate`). It asks for lookups one at a time (customer, account, history, KYC), up to six steps,
   then concludes with **claims**: a finding code from the closed vocabulary plus the observations it cites. Every
   lookup goes through the tool layer under its own role (`investigator_agent`), so permissions, case scope and the
   audit trail are unchanged. It cannot call the execution tools or read policy.
2. **It never sees third-party text.** Merchant names become opaque refs (`m1`, `m2`) so it can still group by
   merchant; memos are dropped; it cannot claim `instruction_text`. A test checks that no merchant name or memo from any
   scenario account reaches a prompt.
3. **Claims are fact-checked against what the model actually looked at.** The baseline analysis always runs. A claim for
   a code the baseline covers is *confirmed* only if the same logic, run on only the history the model fetched, also finds
   it. A claim is dropped (and counted) if it cites nothing, cites an observation that does not exist, or is not supported.
4. **The model may add, never remove or invent.** `possible_structuring` (new, risk, NB-POL-AML-001 section 6) is a
   finding the baseline does not search for. The model may propose it, and it becomes a finding only if the policy's
   criteria hold over the observed history. The verification agent recomputes it again from the numbers it recorded.
5. The platform is never less careful than before: baseline findings are always kept, and a missing, failing or
   endless model leaves exactly the baseline. Each run produces a typed `InquiryReport` (lookups, claimed, confirmed,
   added, dropped, missed) shown on the case and written to the audit log, so agreement with the baseline can be measured.

## Consequences
- Good: the model's work is visible and checkable, it can find what the arithmetic cannot, and every disagreement is data.
  With Groq `gpt-oss-20b` and Gemini, scenario I produced a confirmed `possible_structuring` finding that no earlier
  version found.
- Cost: more tokens and, on a free tier, long waits for rate limits (85 to 250 seconds a case). Opening a case with the
  model on is slow; later stages run it in the background.
- Limit: confirmation reuses the baseline's own thresholds, so the model cannot be *more right* than the baseline on a
  baseline-covered code; what it adds is discovery of new patterns and a measurable second opinion.
