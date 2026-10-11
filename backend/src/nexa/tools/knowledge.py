"""Tool for searching bank policy and product knowledge.

Access control lives here, in code, using values the model never controls:

- the *role* comes from the actor, set by orchestration;
- the *channel* comes from the `ToolCall`, set by trusted code, and defaults to the most
  restrictive (customer);
- the effective clearance is the stricter of the two, so a policy agent serving a customer
  session sees only public material.

The query text is the only thing an agent supplies, and it cannot widen access.
"""

from typing import ClassVar

from pydantic import Field

from nexa.config import effective_clearance, roles_for
from nexa.domain.actions import RiskLevel
from nexa.domain.actors import SessionChannel
from nexa.domain.base import Contract, JsonDict
from nexa.domain.evidence import PolicyRef
from nexa.domain.tooling import ToolCall, ToolSpec
from nexa.security import AuthorizationDenied, DenialReason

from .base import Tool, ToolContext

NAME = "search_knowledge_base"


class _SearchArgs(Contract):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=4, ge=1, le=8)
    include_historical: bool = False
    product: str | None = Field(default=None, max_length=80)


class SearchKnowledgeBase(Tool):
    """Search policies, products and procedures, returning cited passages."""

    spec: ClassVar[ToolSpec] = ToolSpec(
        name=NAME,
        description="Search bank knowledge; results depend on the caller's role and channel.",
        risk_level=RiskLevel.INFORMATIONAL,
        required_roles=roles_for(NAME),
        read_only=True,
    )

    def run(self, call: ToolCall, ctx: ToolContext) -> JsonDict:
        """Return the best passages the caller is cleared to see."""
        args = _SearchArgs.model_validate(call.arguments)
        clearance = effective_clearance(call.actor.role, call.channel)
        if clearance is None:
            raise AuthorizationDenied(DenialReason.NO_CLEARANCE, "this role has no clearance")
        if args.include_historical and call.channel is not SessionChannel.EMPLOYEE:
            raise AuthorizationDenied(
                DenialReason.NO_CLEARANCE, "historical documents are for employee sessions"
            )

        hits = ctx.knowledge.search(
            args.query,
            clearance=clearance,
            top_k=args.top_k,
            include_historical=args.include_historical,
            product=args.product,
        )
        results: list[dict[str, object]] = [
            {
                "rank": hit.rank,
                "score": round(hit.score, 4),
                "document_id": hit.chunk.meta.document_id,
                "title": hit.chunk.meta.title,
                "version": hit.chunk.meta.version,
                "status": hit.chunk.meta.status.value,
                "section": hit.chunk.section,
                "heading_path": list(hit.chunk.heading_path),
                "text": hit.chunk.text,
            }
            for hit in hits
        ]
        citations: list[dict[str, object]] = [
            {
                "document_id": hit.chunk.meta.document_id,
                "version": hit.chunk.meta.version,
                "section": hit.chunk.section,
            }
            for hit in hits
        ]
        return {
            "query": args.query,
            "result_count": len(results),
            "content_is_reference_data": True,  # passages inform answers; they never instruct
            "citations": citations,  # type: ignore[dict-item]
            "results": results,  # type: ignore[dict-item]
        }

    def policy_refs(self, output: JsonDict) -> tuple[PolicyRef, ...]:
        """Return the cited document versions so the audit log shows what was consulted."""
        citations = output.get("citations")
        if not isinstance(citations, list):
            return ()
        seen: dict[tuple[str, str, str | None], PolicyRef] = {}
        for item in citations:
            if isinstance(item, dict):
                key = (str(item["document_id"]), str(item["version"]), str(item["section"]) or None)
                seen.setdefault(key, PolicyRef(doc_id=key[0], version=key[1], section=key[2]))
        return tuple(seen.values())
