---
document_id: NB-POL-AUTH-001
title: Action Authorization Matrix
department: Risk and Control
document_type: Policy
version: 1.0
effective_date: 2026-10-01
status: Active
access_level: Internal Prototype
product: Agentic Operations
jurisdiction: Pakistan Prototype
---

# Action Authorization Matrix (synthetic prototype policy)

This is a synthetic document for the NexaBank prototype. It is not a real bank policy.

## 1. Principle
AI agents investigate and recommend. They never authorize. Authorization is performed by
deterministic controls and, for consequential actions, by named human approvers.

## 2. Approval matrix
| Action | Level | Required approvers | Approval valid for |
| --- | --- | --- | --- |
| No action, monitor, request documents, escalate | 1-2 | None (automatic) | n/a |
| Request customer verification | 3 | Fraud analyst | 240 minutes |
| Block card | 3 | Fraud analyst | 60 minutes |
| Freeze account | 4 | Fraud analyst and risk officer (two different people) | 120 minutes |

## 3. Rules
1. A human who rejects, escalates or asks for modification ends the request.
2. One person cannot satisfy two required roles.
3. An expired approval can never authorize execution; a new request is needed.
4. Execution requires an approval identifier that is valid at the moment of execution.
5. Any agent attempting an action outside its role is denied and the attempt is recorded.

## 4. Role limits
Data and analysis agents can only read. The decision agent sees evidence only. No agent can
freeze an account, block a card or contact a customer.
