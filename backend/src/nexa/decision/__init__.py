"""DecisionProvider interface plus rule-based and LLM implementations.

Why: Ranks candidate actions from structured evidence. Provider is swappable (e.g. a future
    JEV adapter). Output is a recommendation, never an authorization.

Where it sits: Layer 3. Sees evidence objects only, no bank tools.

Modules:
    provider  `DecisionProvider` protocol and the `DecisionRequest` a provider receives
    rules     `RuleBasedDecisionProvider`: policy rules over typed findings, then hard gates (7a)
"""

from .provider import DecisionProvider, DecisionRequest
from .rules import PROVIDER_NAME, RuleBasedDecisionProvider

__all__ = ["PROVIDER_NAME", "DecisionProvider", "DecisionRequest", "RuleBasedDecisionProvider"]
