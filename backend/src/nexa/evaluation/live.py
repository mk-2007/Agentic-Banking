"""A real model against the rules, on the same lab cases, behind the same gates.

The model only proposes a ranking; `LlmDecisionProvider` runs it through the shared hard gates and
falls back to the rules if the model is down or answers badly. This compares the two on each case:
whether they agree, how often the gates had to overrule the model, how often the rules had to take
over, and whether the final recommendation was safe and useful.

Results are small and plain so a run can be saved and shown later. Nothing here holds a key: the
caller builds the gateway from the environment.
"""

import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from nexa.bank_sim.scenarios import ScenarioSpec
from nexa.decision import DecisionRequest, LlmDecisionProvider, RuleBasedDecisionProvider
from nexa.domain.clock import Clock
from nexa.llm import LlmGateway
from nexa.orchestration import CaseRun

from .scoring import judge


@dataclass(frozen=True)
class LiveCase:
    """One case: what the rules and the model each recommended, and how the model's answer fared."""

    case_id: str
    archetype: str
    rules_action: str
    llm_action: str
    agree: bool
    gate: str | None
    fell_back: bool
    safe: bool
    useful: bool
    preferred: bool


@dataclass(frozen=True)
class LiveSummary:
    """The model's results over a run of cases."""

    provider: str
    total: int
    agree: int
    safe: int
    useful: int
    preferred: int
    gate_interventions: int
    fallbacks: int
    seconds: float
    cases: tuple[LiveCase, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a plain dict for saving as JSON."""
        return asdict(self)


def compare_live(
    runs: Sequence[tuple[ScenarioSpec, str, CaseRun]],
    gateway: LlmGateway,
    clock: Clock,
    *,
    provider_label: str,
    limit: int | None = None,
) -> LiveSummary:
    """Run the model (behind the gates) on each finished lab run and compare it with the rules."""
    rules = RuleBasedDecisionProvider(clock)
    provider = LlmDecisionProvider(gateway, clock, rules)
    cases: list[LiveCase] = []
    started = time.perf_counter()
    for spec, archetype, run in list(runs)[:limit]:
        inv, reference = run.investigation, run.decision
        if inv is None or reference is None:
            continue
        request = DecisionRequest(
            case_id=run.case.id,
            findings=inv.findings,
            uncertainty_flags=inv.verification.uncertainty_flags,
            policy_refs=inv.policy.policy_refs,
        )
        decision = provider.decide(request)
        chosen = next(
            c for c in decision.ranked_candidates if c.action == decision.recommended_action
        )
        score = judge(
            spec,
            archetype,
            action=decision.recommended_action,
            justified=bool(chosen.supporting_evidence_ids and decision.policy_refs),
            flags_carried=set(inv.verification.uncertainty_flags)
            <= set(decision.uncertainty_flags),
            flags=tuple(f.value for f in decision.uncertainty_flags),
        )
        cases.append(
            LiveCase(
                case_id=spec.id,
                archetype=archetype,
                rules_action=reference.recommended_action.value,
                llm_action=decision.recommended_action.value,
                agree=decision.recommended_action == reference.recommended_action,
                gate=decision.overridden_by,
                fell_back=decision.provider == "rule_based_v1",
                safe=score.safe,
                useful=score.useful,
                preferred=score.preferred,
            )
        )
    return LiveSummary(
        provider=provider_label,
        total=len(cases),
        agree=sum(c.agree for c in cases),
        safe=sum(c.safe for c in cases),
        useful=sum(c.useful for c in cases),
        preferred=sum(c.preferred for c in cases),
        gate_interventions=sum(c.gate is not None for c in cases),
        fallbacks=sum(c.fell_back for c in cases),
        seconds=round(time.perf_counter() - started, 1),
        cases=tuple(cases),
    )
