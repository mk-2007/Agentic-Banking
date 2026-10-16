"""The hard gates every decision provider must pass, whoever proposes the action.

A provider (rules, an LLM, a future JEV adapter) only *proposes*. These checks are plain code that
decide whether a proposed action may be recommended for this case, and name the gate that
refused it. They are shared so that no provider can be looser than another.

Gates, in the order they are checked:
- ``uncertainty_gate``: missing or conflicting evidence allows only cautious actions;
- ``no_action_gate``: "no action" is only for cases with no risk finding (NB-POL-FRAUD-001
  section 5);
- ``justification_gate``: a Level 3+ action needs supporting findings (at least one a risk finding)
  and a cited clause from the document that governs that response;
- ``pattern_gate``: freezing an account or blocking a card needs the indicator pattern the fraud
  policy describes for it (below), so one weak finding, or text that only tries to instruct the
  investigation, can never justify a restriction.
"""

from collections.abc import Collection, Mapping
from types import MappingProxyType
from typing import Final

from nexa.domain.actions import ACTION_RISK_LEVEL, UNCERTAINTY_SAFE_ACTIONS, ActionType
from nexa.domain.decision import BLOCKING_UNCERTAINTY, UncertaintyFlag
from nexa.domain.evidence import PolicyRef
from nexa.domain.indicators import IndicatorCode

FRAUD, AML, AUTH = "NB-POL-FRAUD-001", "NB-POL-AML-001", "NB-POL-AUTH-001"
C = IndicatorCode

# Indicators that together describe an account takeover (NB-POL-FRAUD-001 section 2). Our reading of
# the policy: the prototype policy names the indicators but not the freeze condition.
TAKEOVER_SIGNS = (C.RAPID_SERIES, C.NEW_BENEFICIARY, C.UNKNOWN_DEVICE, C.FAILED_AUTH)
TAKEOVER_MINIMUM = 3

A = ActionType
# The policy documents that govern each response (NB-POL-FRAUD-001 section 5, NB-POL-AUTH-001).
GOVERNING_DOCUMENTS: Final[Mapping[ActionType, tuple[str, ...]]] = MappingProxyType(
    {
        A.NO_ACTION: (),
        A.MONITOR_ACCOUNT: (FRAUD,),
        A.REQUEST_KYC_DOCUMENTS: (AML,),
        A.ESCALATE_TO_ANALYST: (FRAUD,),
        A.REQUEST_CUSTOMER_VERIFICATION: (AML, FRAUD),
        A.BLOCK_CARD: (FRAUD, AUTH),
        A.FREEZE_ACCOUNT: (FRAUD, AUTH),
    }
)


def governing_refs(action: ActionType, refs: tuple[PolicyRef, ...]) -> tuple[PolicyRef, ...]:
    """Keep the retrieved clauses that come from the documents governing ``action``."""
    documents = GOVERNING_DOCUMENTS[action]
    return tuple(dict.fromkeys(r for r in refs if r.doc_id in documents))


def restriction_supported(
    action: ActionType, codes: Collection[IndicatorCode], *, mitigated: bool
) -> bool:
    """Return whether the findings in ``codes`` form the pattern that ``action`` requires.

    Only freezing and card blocking have a pattern; every other action returns True here.
    ``mitigated`` is whether any mitigating finding (travel notice, trusted device...) exists.
    """
    present = set(codes)
    if action is ActionType.FREEZE_ACCOUNT:
        return len(present & set(TAKEOVER_SIGNS)) >= TAKEOVER_MINIMUM and not mitigated
    if action is ActionType.BLOCK_CARD:
        return C.CARD_TESTING in present or {C.AMOUNT_ABOVE_AVERAGE, C.UNUSUAL_GEOGRAPHY} <= present
    return True


def refusal(
    action: ActionType,
    *,
    support_ids: Collection[str],
    risk_ids: Collection[str],
    refs: tuple[PolicyRef, ...],
    flags: Collection[UncertaintyFlag],
    case_codes: Collection[IndicatorCode],
    mitigated: bool,
) -> str | None:
    """Return the name of the gate that refuses ``action`` here, or None if it may go ahead.

    ``support_ids`` are the findings offered in support; ``risk_ids`` is every risk finding;
    ``case_codes`` are the codes of every finding in the case.
    """
    if BLOCKING_UNCERTAINTY & set(flags) and action not in UNCERTAINTY_SAFE_ACTIONS:
        return "uncertainty_gate"
    if action is ActionType.NO_ACTION and risk_ids:
        return "no_action_gate"
    if ACTION_RISK_LEVEL[action].requires_human_approval and not (
        set(support_ids) & set(risk_ids) and governing_refs(action, refs)
    ):
        return "justification_gate"
    if not restriction_supported(action, case_codes, mitigated=mitigated):
        return "pattern_gate"
    return None
