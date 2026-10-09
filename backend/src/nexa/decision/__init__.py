"""DecisionProvider interface plus rule-based and LLM implementations.

Why: Ranks candidate actions from structured evidence. Provider is swappable (e.g. a future
    JEV adapter). Output is a recommendation, never an authorization.

Where it sits: Layer 3. Sees evidence objects only, no bank tools.
"""
