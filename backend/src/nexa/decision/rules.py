"""The rule-based decision provider: transparent rules over typed findings, then hard gates.

Why rules first: the policies (NB-POL-FRAUD-001, NB-POL-AML-001, NB-POL-AUTH-001) already say which
indicators justify which response, so the baseline can be read, tested and explained line by line.
An LLM provider (7b) is later measured against this one.

How it decides, in order:
1. Each rule that fires proposes one action with a fixed ranking score and the findings behind it.
2. Candidates are ranked best-first. The scores only order candidates; they are not probabilities.
3. Two hard gates pick the recommendation from the ranking, and say so (``overridden_by``) when they
   skip the top one: blocking uncertainty allows only cautious actions, and a Level 3+ action needs
   supporting findings and a cited policy from the document that governs it.
4. Escalating to an analyst is always available as the safe fallback.

Third-party text never reaches this layer: it sees finding codes, evidence ids and policy refs.
"""

from collections.abc import Callable
from dataclasses import dataclass

from nexa.domain.actions import ACTION_RISK_LEVEL, ActionType
from nexa.domain.clock import Clock
from nexa.domain.decision import BLOCKING_UNCERTAINTY, CandidateScore, Decision, UncertaintyFlag
from nexa.domain.evidence import Evidence
from nexa.domain.indicators import IndicatorCode

from .facts import Facts, read_facts, unique_ids
from .gates import TAKEOVER_SIGNS, governing_refs, refusal, restriction_supported
from .provider import DecisionRequest

PROVIDER_NAME = "rule_based_v1"
C = IndicatorCode

KYC_GAPS = (C.KYC_ITEM_MISSING, C.KYC_NOT_VERIFIED)


@dataclass(frozen=True)
class _Rule:
    name: str
    action: ActionType
    score: float
    fires: Callable[[Facts], tuple[Evidence, ...]]  # the findings that justify it, or none


def _takeover(f: Facts) -> tuple[Evidence, ...]:
    if not restriction_supported(ActionType.FREEZE_ACCOUNT, f.codes, mitigated=bool(f.mitigating)):
        return ()
    return f.of(*(code for code in TAKEOVER_SIGNS if f.has(code)))


def _card_fraud(f: Facts) -> tuple[Evidence, ...]:
    if not restriction_supported(ActionType.BLOCK_CARD, f.codes, mitigated=bool(f.mitigating)):
        return ()
    if f.has(C.CARD_TESTING):
        return f.of(C.CARD_TESTING)
    return f.of(C.AMOUNT_ABOVE_AVERAGE, C.UNUSUAL_GEOGRAPHY)


RULES: tuple[_Rule, ...] = (
    _Rule("account_takeover", ActionType.FREEZE_ACCOUNT, 0.95, _takeover),
    _Rule("card_fraud", ActionType.BLOCK_CARD, 0.85, _card_fraud),
    _Rule("kyc_gap", ActionType.REQUEST_KYC_DOCUMENTS, 0.80, lambda f: f.of(*KYC_GAPS)),
    _Rule(
        "identity_mismatch",
        ActionType.REQUEST_CUSTOMER_VERIFICATION,
        0.70,
        lambda f: f.of(C.KYC_ADDRESS_MISMATCH),
    ),
    _Rule(
        "possible_structuring",
        ActionType.ESCALATE_TO_ANALYST,
        0.60,
        lambda f: f.of(C.POSSIBLE_STRUCTURING),
    ),
    _Rule(
        "several_indicators",
        ActionType.ESCALATE_TO_ANALYST,
        0.50,
        lambda f: f.risk if len(f.risk) >= 2 else (),
    ),
    _Rule("any_indicator", ActionType.MONITOR_ACCOUNT, 0.40, lambda f: f.risk),
    _Rule("no_indicator", ActionType.NO_ACTION, 0.90, lambda f: f.info if not f.risk else ()),
)
FALLBACK = ActionType.ESCALATE_TO_ANALYST
FALLBACK_SCORE = 0.05


@dataclass(frozen=True)
class _Candidate:
    rule: _Rule | None  # None for the safe fallback
    action: ActionType
    score: float
    support: tuple[str, ...]
    against: tuple[str, ...]


class RuleBasedDecisionProvider:
    """Recommends one action from a closed set, with the evidence and policy behind it."""

    name = PROVIDER_NAME

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def decide(self, request: DecisionRequest) -> Decision:
        """Rank the actions the rules support and recommend the first one the gates allow."""
        facts = read_facts(request.findings)
        flags = request.uncertainty_flags
        candidates = self._rank(facts, flags)
        top = candidates[0]
        risk_ids = unique_ids(facts.risk)
        chosen, gate = top, None
        for candidate in candidates:
            problem = refusal(
                candidate.action,
                support_ids=candidate.support,
                risk_ids=risk_ids,
                refs=request.policy_refs,
                flags=flags,
                case_codes=facts.codes,
                mitigated=bool(facts.mitigating),
            )
            if problem is None:
                chosen = candidate
                break
            gate = gate or problem
        action = chosen.action
        refs = governing_refs(action, request.policy_refs)
        return Decision(
            id=f"dec_{request.case_id}",
            case_id=request.case_id,
            ranked_candidates=tuple(
                CandidateScore(
                    action=c.action,
                    score=c.score,
                    supporting_evidence_ids=c.support,
                    opposing_evidence_ids=tuple(i for i in c.against if i not in c.support),
                )
                for c in candidates
            ),
            recommended_action=action,
            overridden_by=gate if chosen is not top else None,
            risk_level=ACTION_RISK_LEVEL[action],
            approval_required=ACTION_RISK_LEVEL[action].requires_human_approval,
            uncertainty_flags=flags,
            evidence_strength=min(1.0, len(chosen.support) / 4),
            policy_refs=refs,
            provider=self.name,
            created_at=self._clock(),
        )

    def _rank(self, facts: Facts, flags: tuple[UncertaintyFlag, ...]) -> list[_Candidate]:
        against = unique_ids(facts.mitigating)
        found: dict[ActionType, _Candidate] = {}
        for rule in RULES:
            support = unique_ids(rule.fires(facts))
            if not support:
                continue
            candidate = _Candidate(
                rule,
                rule.action,
                rule.score,
                support,
                () if rule.name == "no_indicator" else against,
            )
            if rule.action not in found or candidate.score > found[rule.action].score:
                found[rule.action] = candidate
        if BLOCKING_UNCERTAINTY & set(flags) and FALLBACK not in found:
            found[FALLBACK] = _Candidate(None, FALLBACK, 0.50, unique_ids(facts.risk), against)
        if FALLBACK not in found:  # always keep a safe way out, ranked last
            found[FALLBACK] = _Candidate(
                None, FALLBACK, FALLBACK_SCORE, unique_ids(facts.risk), against
            )
        return sorted(found.values(), key=lambda c: (-c.score, c.action.value))
