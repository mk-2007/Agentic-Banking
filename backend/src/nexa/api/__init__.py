"""FastAPI routes: thin HTTP layer only.

Why: No business logic here; it validates input and delegates to orchestration (PRD sections
    35, 46).

Where it sits: Layer 5 (top). May import anything.
"""
