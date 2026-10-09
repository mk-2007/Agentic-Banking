# ADR 0001: Layered architecture; the tool layer enforces security

- Status: accepted
- Date: 2026-10-09

## Context
The platform lets LLM agents act on banking data. LLM output is untrusted and can be manipulated
(for example by prompt injection hidden in a merchant name).

## Decision
1. Code is organised in strict layers; imports are checked by an automated test.
2. Agents never call the bank directly. Every access goes through `tools`.
3. Permission checks and audit logging happen **inside the tool layer**, in plain code, not in prompts.
4. Authorization is never delegated to an LLM.

## Consequences
- Good: a compromised or confused agent cannot exceed its role; behaviour is testable without any model.
- Good: easy for reviewers to see where trust boundaries are.
- Cost: a little more boilerplate per tool.
