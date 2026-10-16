# ADR 0010: Model decisions share the hard gates and keep a human floor

- Status: accepted
- Date: 2026-10-16

## Context
Phase 7b let a model rank actions. The first evaluation (7c) put misbehaving stand-in models through the
gates and found two holes: a "reckless" model could get `freeze_account` recommended on an incomplete-KYC case
and on a prompt-injection case, because the justification gate only asked for *some* cited risk finding; and a
"lazy" model could turn a card-testing case and an account takeover into `monitor_account`, so nobody looked
at them.

## Decision
1. Every provider is checked by the same code (`decision/gates.py`), in order: `uncertainty_gate`,
   `no_action_gate`, `justification_gate`, `pattern_gate`. A provider only proposes.
2. Freezing an account needs at least three takeover indicators (rapid series, new beneficiary, unknown
   device, failed authentication) and no mitigating finding. Blocking a card needs card testing, or an
   unusual amount together with unusual geography. The rule provider and the gate read one definition
   (`restriction_supported`), so they cannot drift. Text that only tries to instruct the investigation
   (`instruction_text`) never satisfies a pattern.
3. A model decision has a human floor: if the baseline provider would involve a person (an approval or an
   analyst hand-off), the model may not recommend an action that involves nobody. It may be more cautious
   than the baseline, never less.

## Consequences
- Good: a model cannot get a restriction recommended on thin or hostile evidence, nor quietly downgrade a
  serious case. The evaluation proves it for a reckless and a lazy stand-in, and a test fails if a gate is
  removed.
- Cost: the model's room to add value is narrowed to ranking among acceptable cautious actions, so 7d must
  say how much of any LLM-versus-rules difference is the model and how much is the gates.
- The indicator patterns are our reading of NB-POL-FRAUD-001; the prototype policy names the indicators but
  not the freeze condition. Changing the pattern means changing one function and its tests.
