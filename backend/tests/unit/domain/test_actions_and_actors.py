import pytest
from pydantic import ValidationError

from nexa.domain.actions import ACTION_RISK_LEVEL, ActionType, RiskLevel
from nexa.domain.actors import Actor, ActorKind, Role


def test_every_action_has_a_risk_level() -> None:
    assert set(ACTION_RISK_LEVEL) == set(ActionType)


def test_freeze_is_the_only_level_four_action() -> None:
    level_four = [a for a, level in ACTION_RISK_LEVEL.items() if level is RiskLevel.HIGH_RISK]
    assert level_four == [ActionType.FREEZE_ACCOUNT]


@pytest.mark.parametrize(
    ("level", "needs_human"),
    [
        (RiskLevel.INFORMATIONAL, False),
        (RiskLevel.LOW_OPERATIONAL, False),
        (RiskLevel.SENSITIVE, True),
        (RiskLevel.HIGH_RISK, True),
    ],
)
def test_human_approval_threshold(level: RiskLevel, needs_human: bool) -> None:
    assert level.requires_human_approval is needs_human


def test_actor_role_must_fit_kind() -> None:
    Actor(kind=ActorKind.USER, id="u", role=Role.FRAUD_ANALYST)
    Actor(kind=ActorKind.AGENT, id="a", role=Role.DATA_AGENT)
    Actor(kind=ActorKind.SYSTEM, id="sys")
    with pytest.raises(ValidationError):
        Actor(kind=ActorKind.AGENT, id="a", role=Role.FRAUD_ANALYST)
    with pytest.raises(ValidationError):
        Actor(kind=ActorKind.USER, id="u", role=Role.DATA_AGENT)
    with pytest.raises(ValidationError):
        Actor(kind=ActorKind.SYSTEM, id="sys", role=Role.DATA_AGENT)
    with pytest.raises(ValidationError):
        Actor(kind=ActorKind.USER, id="u")
