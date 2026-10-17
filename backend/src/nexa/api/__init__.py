"""FastAPI routes: thin HTTP layer only.

Why: No business logic here; it validates input and delegates to orchestration (PRD sections
    35, 46).

Where it sits: Layer 5 (top). May import anything.

Modules:
    lab         `LabService`: runs labelled cases and scores them (auditor only)
    principals  bearer tokens to a user and role; the role decides the session channel
    service     `CaseService`: wires the platform and runs cases, votes and chat
    schemas     request and response shapes (no dossier, no third-party text)
    app         `create_app`: the routes
"""

from .app import create_app
from .lab import LabService
from .principals import Principal, demo_tokens, parse_tokens
from .service import CaseService

__all__ = ["CaseService", "LabService", "Principal", "create_app", "demo_tokens", "parse_tokens"]
