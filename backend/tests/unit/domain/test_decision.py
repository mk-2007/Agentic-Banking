import pytest
from builders import make_decision
from pydantic import ValidationError

from nexa.domain.actions import ActionType, RiskLevel
from nexa.domain.decision import CandidateScore, UncertaintyFlag


def test_valid_low_risk_decision() -> None:
    d = make_decision(ActionType.ESCALATE_TO_ANALYST)
    assert d.risk_level is RiskLevel.LOW_OPERATIONAL
    assert d.approval_required is False


def test_freeze_decision_requires_approval() -> None:
    d = make_decision(ActionType.FREEZE_ACCOUNT)
    assert d.risk_level is RiskLevel.HIGH_RISK
    assert d.approval_required is True


def test_ranking_must_be_sorted_best_first() -> None:
    ranked = (
        CandidateScore(action=ActionType.ESCALATE_TO_ANALYST, score=0.2),
        CandidateScore(action=ActionType.NO_ACTION, score=0.8),
    )
    with pytest.raises(ValidationError, match="sorted"):
        make_decision(ActionType.ESCALATE_TO_ANALYST, ranked=ranked)


def test_actions_cannot_repeat_in_ranking() -> None:
    ranked = (
        CandidateScore(action=ActionType.NO_ACTION, score=0.8),
        CandidateScore(action=ActionType.NO_ACTION, score=0.2),
    )
    with pytest.raises(ValidationError, match="only once"):
        make_decision(ActionType.NO_ACTION, ranked=ranked)


def test_recommendation_must_be_a_candidate() -> None:
    ranked = (CandidateScore(action=ActionType.NO_ACTION, score=0.9),)
    with pytest.raises(ValidationError, match="ranked candidates"):
        make_decision(ActionType.ESCALATE_TO_ANALYST, ranked=ranked)


def test_lower_ranked_recommendation_needs_a_named_gate() -> None:
    ranked = (
        CandidateScore(action=ActionType.NO_ACTION, score=0.9),
        CandidateScore(action=ActionType.ESCALATE_TO_ANALYST, score=0.1),
    )
    with pytest.raises(ValidationError, match="overridden_by"):
        make_decision(ActionType.ESCALATE_TO_ANALYST, ranked=ranked)
    d = make_decision(
        ActionType.ESCALATE_TO_ANALYST, ranked=ranked, overridden_by="insufficient_evidence_gate"
    )
    assert d.overridden_by == "insufficient_evidence_gate"


@pytest.mark.parametrize(
    "flag", [UncertaintyFlag.INSUFFICIENT_EVIDENCE, UncertaintyFlag.CONFLICTING_EVIDENCE]
)
@pytest.mark.parametrize(
    "action", [ActionType.NO_ACTION, ActionType.BLOCK_CARD, ActionType.FREEZE_ACCOUNT]
)
def test_uncertain_evidence_forbids_non_cautious_actions(
    flag: UncertaintyFlag, action: ActionType
) -> None:
    with pytest.raises(ValidationError, match="only escalation"):
        make_decision(action, flags=(flag,))


def test_uncertain_evidence_allows_escalation() -> None:
    d = make_decision(ActionType.ESCALATE_TO_ANALYST, flags=(UncertaintyFlag.CONFLICTING_EVIDENCE,))
    assert d.recommended_action is ActionType.ESCALATE_TO_ANALYST


def test_consequential_action_needs_supporting_evidence_and_policy() -> None:
    with pytest.raises(ValidationError, match="supporting evidence"):
        make_decision(ActionType.FREEZE_ACCOUNT, supporting=())
    with pytest.raises(ValidationError, match="cite at least one policy"):
        make_decision(ActionType.FREEZE_ACCOUNT, policy_refs=())


def test_mismatched_risk_level_is_rejected() -> None:
    good = make_decision(ActionType.FREEZE_ACCOUNT)
    with pytest.raises(ValidationError, match="risk_level"):
        type(good)(**{**good.model_dump(), "risk_level": RiskLevel.INFORMATIONAL})


def test_scores_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        CandidateScore(action=ActionType.NO_ACTION, score=1.5)


def test_evidence_cannot_both_support_and_oppose() -> None:
    with pytest.raises(ValidationError, match="both support and oppose"):
        CandidateScore(
            action=ActionType.NO_ACTION,
            score=0.5,
            supporting_evidence_ids=("ev_1",),
            opposing_evidence_ids=("ev_1",),
        )


def test_decision_round_trips_through_json() -> None:
    d = make_decision(ActionType.FREEZE_ACCOUNT)
    assert type(d).model_validate_json(d.model_dump_json()) == d
