# ADR 0007: One OpenAI-compatible adapter; the gateway owns reliability and validation

- Status: accepted
- Date: 2026-10-13

## Context
We have free-tier keys for Groq and Gemini, both with OpenAI-compatible endpoints, and want to stay able to
swap providers (ADR 0002 already makes decision providers swappable). Free tiers rate-limit, models change
names, and language models sometimes return malformed JSON.

## Decision
1. Implement one `OpenAiCompatibleProvider` and describe providers as configuration presets.
2. Put reliability in a `LlmGateway`: retries with backoff, failover across providers, and a per-case token budget.
3. Never trust model output: structured calls are validated against a Pydantic schema, with bounded repair attempts.
4. Keys come only from the environment and never appear in errors, logs or audit data.
5. Test everything against a simulated HTTP server and a scripted fake provider, so CI needs no keys or network.

## Consequences
- Good: both providers work immediately, a free-tier outage degrades to the other provider, and agents can be
  tested deterministically with `ScriptedProvider`.
- Good: cost and loops are bounded in code.
- Cost: live behaviour is only proven by running the smoke script with real keys; provider quirks may need small
  adapter changes.
