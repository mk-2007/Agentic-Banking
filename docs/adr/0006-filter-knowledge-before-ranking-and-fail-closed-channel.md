# ADR 0006: Filter knowledge before ranking; the session channel is trusted input that fails closed

- Status: accepted
- Date: 2026-10-12

## Context
The same knowledge base serves a customer chatbot and employee investigators. Restricted documents hold
detection thresholds that must never reach customers (KB section 17.6). A single customer-facing mistake,
such as routing a customer chat through a more privileged agent, must not leak them.

## Decision
1. Sensitivity (public, internal, restricted) is metadata on every chunk, set in document front matter with
   per-section overrides.
2. Clearance is the stricter of the caller's role clearance and the session channel's cap, both configuration.
3. There is one search index per clearance level. Unauthorized chunks are not in the index being queried, so
   filtering happens before ranking, not after.
4. The channel is a field on `ToolCall` set by trusted code, never by a model, and defaults to customer.
5. Start with BM25 plus a curated synonym list. Dense retrieval is deferred until an evaluation shows the need.

## Consequences
- Good: no side channel through scores or counts; forgetting the channel is safe; customer service agents stay
  public even on employee sessions.
- Good: no model downloads, so ingestion and tests are deterministic and offline.
- Cost: three indexes in memory (trivial at this size); lexical search misses unseen wording.
