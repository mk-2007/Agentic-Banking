"""DecisionProvider interface plus rule-based and LLM implementations.

Why: Ranks candidate actions from structured evidence. Provider is swappable (e.g. a future
    JEV adapter). Output is a recommendation, never an authorization.

Where it sits: Layer 3. Sees evidence objects only, no bank tools.

Modules:
    provider  `DecisionProvider` protocol and the `DecisionRequest` a provider receives
    facts     reading findings: the typed facts a provider may see
    gates     the hard gates every provider must pass (uncertainty, no-action, justification)
    rules     `RuleBasedDecisionProvider`: policy rules over typed findings, then the gates (7a)
    llm_provider  `LlmDecisionProvider`: a model proposes a ranking, the gates decide (7b)
"""

from .gates import refusal
from .llm_provider import LlmChoice, LlmDecisionProvider
from .provider import DecisionProvider, DecisionRequest
from .rules import PROVIDER_NAME, RuleBasedDecisionProvider

__all__ = [
    "PROVIDER_NAME",
    "DecisionProvider",
    "DecisionRequest",
    "LlmChoice",
    "LlmDecisionProvider",
    "RuleBasedDecisionProvider",
    "refusal",
]
