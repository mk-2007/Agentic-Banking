# ADR 0011: An auditor role and a private evaluation lab

- Status: accepted
- Date: 2026-10-17

## Context
To show how good the agents are, we want to run them on many labelled synthetic accounts and report the
results. That needs three things the platform did not have: a larger labelled dataset, a place to score
runs, and a screen for it. Doing this on the live case desk would mix test cases into real work, and giving
the same people the lab and the vote would let one person both judge the system and steer it.

## Decision
1. A new human role, `auditor`. It can sign in, use the `/admin/lab` and `/admin/accounts` endpoints and read
   reports. It cannot open live cases, vote, or call tools: it is not an employee role, not an approver
   role, and has no tool or knowledge clearance (deny by default). The check is plain code in the API.
2. The lab runs on its own `CaseService` over its own bank (core data plus the lab cohort), so lab runs
   never appear among, or change, live cases or the live audit log.
3. Ground truth is separate from the bank. The labelled cohort lives in `data/synthetic/lab/` and each
   case's label is in `lab_cases.json`, which only the scoring code reads; agents reach the bank only
   through tools, as before. The core dataset and its ids are untouched.
4. Scoring is a new package, `evaluation`, that reads a finished case run and its label and changes
   nothing. It sits above `orchestration` and below `api`.
5. Lab responses follow the API rule: codes, ids and our own summaries, never merchant names or memos.

## Consequences
- Good: a presentable scorecard and per-account report, repeatable offline (rule-based provider), with
  the authority to run it held by one narrow role.
- Cost: lab cases are variants of the scenario types the thresholds were designed around, so a high pass
  rate shows consistency inside those regimes, not performance on unseen real traffic. Labels also come
  from our reading of the policy and can be wrong; one was widened after the first run (see the log).
- The lab does not execute approved actions; it stops where the live desk waits for votes.
