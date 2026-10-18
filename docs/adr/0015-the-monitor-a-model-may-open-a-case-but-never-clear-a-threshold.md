# ADR 0015: The monitor: a model may open a case, never clear a threshold crossing

- Status: accepted
- Date: 2026-10-18

## Context
Cases came from a button. Real systems watch transactions, and a bank cannot investigate every payment or miss the
ones that matter. Putting a model in front of every payment is slow and, on a free tier, rate-limited; putting it in
charge of dismissing alerts would let a model's mistake hide fraud.

## Decision
1. Every payment posted in the customer app is reviewed by a **monitor**, in the background (the payment is answered
   first). It builds a typed **digest** from the bank's records: numbers and flags only, no merchant name or memo.
2. Three paths, in order. **Floor** (code): a payment that crosses a policy threshold (high value, 5x the customer's
   usual, 5 payments in an hour, 3 failed logins, a new payee on an unknown device) always opens a case, and no model
   is asked. **Routine** (code): a payment that is ordinary in every respect is cleared, by a deliberately narrow rule.
   **Grey zone**: everything else goes to a model, which opens or clears it with a reason from a closed list.
3. **A missing, failing or invalid model opens the case.** The monitor fails toward caution.
4. A burst on one account does not open a case per payment: while a monitor case is recent (4 hours), later payments
   with the same reasons are linked to it, and a reason it did not have (the fifth payment in an hour) opens a new one.
5. The review runs on one background worker. `CaseService` no longer holds one lock while a case runs: a lock guards the
   shared maps briefly and each case runs under its own, so a slow investigation does not stop anyone listing cases or
   voting on another.
6. The log (`GET /monitor/log`, employees only) holds codes and ids only.

## Consequences
- Good: cases are opened by the system from live payments, bounded in cost, and the model's only power is to *add*
  attention in the grey zone, never to remove it where a threshold was crossed.
- Cost: the routine rule and the floor are our reading of the thresholds, so a payment that is dangerous but looks
  ordinary in every digest field is cleared. The model only sees what the digest holds.
- Limit: one worker means investigations queue; with a free-tier model a burst takes minutes to work through.
