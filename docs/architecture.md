# Architecture

> Status: scaffold. Layers exist as documented empty packages; behaviour arrives phase by phase (see README roadmap).

## Principle: controlled autonomy

Agents may investigate and **recommend**. They may not **authorize** anything consequential.
Authorization is deterministic code plus, for risky actions, named humans. This follows the PRD
(`docs/source/PRD_technical_architecture.docx`).

## Layers and the dependency rule

```
Layer 5  api            thin HTTP, no business logic
Layer 4  orchestration  LangGraph graph + case state machine
Layer 3  agents | decision | approvals
Layer 2  tools | rag
Layer 1  security | audit | bank_sim | llm
Layer 0  domain | config
```

A package may import only from the packages listed for it in
`backend/tests/architecture/test_layer_rules.py`. Notable consequences:

- `agents` and `decision` cannot import `bank_sim`. Agents reach the bank **only through `tools`**.
- `tools` enforces permission checks and writes audit events itself, so a misbehaving prompt cannot bypass them.
- `domain` imports nothing, so every layer can share its models safely.

The rule is enforced in CI. Changing it requires a new ADR in `docs/adr/`.

## Request flow (target design)

1. An alert or request enters through `api` and becomes a `Case`.
2. `orchestration` runs the case state machine; the supervisor agent picks which specialist agents are needed.
3. Data/analysis agents gather evidence **through tools**; the policy agent retrieves versioned policy through `rag`.
4. The verification step checks that every claim traces to a tool result or policy chunk.
5. `decision` ranks a **closed set** of candidate actions from structured evidence (see ADR 0002).
6. `security` assigns the action's risk level and required approvers; hard gates can override the ranking.
7. `approvals` pauses the graph for a human on Level 3-4 actions.
8. Only an approved, unexpired approval ID lets `tools` execute the action. Every step is written to `audit`.

## Two channels, one platform

- **Investigation channel** (employees): the flow above.
- **Customer chatbot channel**: read-only tools, customer-authenticated, answers from the NexaBank knowledge base, never exposes detection logic.
