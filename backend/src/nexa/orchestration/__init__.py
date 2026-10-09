"""The LangGraph graph and case state machine.

Why: Coordinates agents, enforces loop limits and pauses for human approval (PRD sections
    37-39).

Where it sits: Layer 4. Composes agents, approvals and decision.
"""
