# ADR 0008: Agents exchange typed findings; analysis is deterministic; the model step is guarded

- Status: accepted
- Date: 2026-10-14

## Context
Agents could pass prose to each other and let a model do the analysis. That is flexible but gives a
model arithmetic it does poorly, lets third-party text (merchant names, memos) travel between agents, and
leaves nothing for a verification step to recompute. The scenarios include a prompt-injection memo.

## Decision
1. Agents exchange `Evidence`. A finding is evidence whose `data` carries a code from the closed
   `IndicatorCode` set, a signal, and the ids it was derived from. There is no free-text channel.
2. Analysis, data retrieval and verification are plain code over the thresholds in `FraudThresholds`.
   Verification recomputes each finding from the numbers it recorded.
3. A model is used in one place: the policy agent may narrow retrieved clauses. It can choose only refs the
   tool returned, sees clause text fenced as untrusted, never sees merchant names or memos, and any failure
   falls back to keeping every retrieved clause.
4. `AgentContext.channel` has no default. A policy topic is covered only when its governing policy was
   retrieved.

## Consequences
- Good: the same case always yields the same findings; an injected memo has no field to land in; a
  forged finding is caught; the whole evaluation runs offline with no key.
- Cost: every new indicator is code plus a policy sentence plus a test; the vocabulary is closed on purpose.
  Language understanding (paraphrased injection, unusual merchants) is weaker than a model's.
- No layer rule changes: agents still import only `domain`, `config`, `llm`, `rag`, `tools`, `decision`.
