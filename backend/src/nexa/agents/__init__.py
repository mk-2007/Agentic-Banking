"""Specialist agents: data, analysis, policy and verification (more arrive with later phases).

Why: Each agent has exactly one job and only the tools its role permits (PRD section 10). They pass
each other typed evidence, never free text, and they never hold a bank connection.

Where it sits: Layer 3. Talks to the world exclusively through tools.

Modules:
    base          `AgentContext` (trusted settings) and `ToolSession` (tool calls under one role)
    findings      the closed set of finding codes and how a finding is stored as evidence
    dossier       typed facts gathered by the data agent
    data_agent    fetches the case records and records them as evidence
    analysis_agent  recomputable indicators against the customer's own history
    investigator_agent  a model that chooses its lookups and proposes findings
    agentic_analysis  checks the model's proposals against what it saw; merges with the baseline
    inquiry       the typed report of how an investigation went
    policy_agent  cited policy clauses; a model may narrow them, under guard rails
    verification_agent  re-checks the findings and sets the uncertainty flags
    investigation a straight-line run of the four (the orchestrator replaces it in phase 6)
"""

from .agentic_analysis import AgenticAnalysis, AnalysisOutcome
from .analysis_agent import AnalysisAgent, derive_findings
from .base import AgentContext, AgentToolError, ToolSession, agent_actor
from .data_agent import AgentDataError, DataAgent
from .dossier import Dossier
from .findings import SIGNAL_OF, IndicatorCode, Signal, code_of, signal_of
from .inquiry import InquiryOutcome, InquiryReport
from .investigation import Investigation, investigate
from .investigator_agent import InvestigatorAgent
from .policy_agent import PolicyAgent, PolicyResult
from .verification_agent import (
    IssueCode,
    VerificationAgent,
    VerificationIssue,
    VerificationReport,
)

__all__ = [
    "SIGNAL_OF",
    "AgentContext",
    "AgentDataError",
    "AgentToolError",
    "AgenticAnalysis",
    "AnalysisAgent",
    "AnalysisOutcome",
    "DataAgent",
    "Dossier",
    "IndicatorCode",
    "InquiryOutcome",
    "InquiryReport",
    "Investigation",
    "InvestigatorAgent",
    "IssueCode",
    "PolicyAgent",
    "PolicyResult",
    "Signal",
    "ToolSession",
    "VerificationAgent",
    "VerificationIssue",
    "VerificationReport",
    "agent_actor",
    "code_of",
    "derive_findings",
    "investigate",
    "signal_of",
]
