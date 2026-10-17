# How it works, start to end (the plain version)

**One sentence:** when a bank transaction looks suspicious, a small team of AI agents investigates it and
*recommends* what to do, plain code checks the recommendation against rules, and a *human* has to approve
anything serious before it happens.

The motto on the page says the same thing: **agents recommend, code enforces, humans authorize.**

## The story of one case (scenario F, account takeover)

| # | What happens | Who does it | Page stage |
|---|---|---|---|
| 0 | An **alert** arrives: "6 transfers in 25 minutes from a new device after failed logins" | the bank's monitoring | (you click *Run investigation*) |
| 1 | **Data agent** fetches facts: the customer, the account, recent transactions. It can only reach the bank through permission-checked *tools*. | agent | 01 Data agent |
| 2 | **Analysis agent** turns the facts into **typed findings** such as `rapid_series`, `unknown_device`, `failed_auth`. Codes, not free text. | agent | 02 Analysis agent |
| 3 | **Policy agent** finds the bank policy clauses that apply (e.g. NB-POL-FRAUD-001 §2) so the answer can cite its rules. | agent | 03 Policy agent |
| 4 | **Verifier** checks that what the agents claim matches the actual facts. | code | 04 Verifier |
| 5 | **Decision** ranks possible actions (freeze account, block card, escalate, no action...) and recommends one. It only *advises*. | rules (or an LLM, then the same rules) | 05 Decision |
| 6 | **Gates** can overrule the pick, for example "a freeze needs 3 takeover signs and not-mitigating evidence", or "if the evidence conflicts, only escalate". | plain code, never an AI | 06 Gate |
| 7 | **Approval** is requested. A freeze is Level 4, so it needs **two different roles**: Fraud Analyst and Risk Officer. | code | Approval card |
| 8 | **Humans vote** (approve, reject, escalate, modify). Your role comes from your token. One role voting twice is still one seat. | people | 07 Humans |
| 9 | **Executor** performs the action only when it holds an *approved* approval id. Nothing else can touch the account. | code | 08 Executor |
| 10 | The case is **verified and closed**. | code | 09 Closed |

Every step above writes an **audit event**, and each event is hash-linked to the one before it, so the log
is tamper-evident. That is the ribbon of coloured blocks at the bottom of the page.

## Who needs to approve what

| Action | Level | Approvers needed |
|---|---|---|
| No action | 1 | none |
| Monitor, request KYC documents, escalate to analyst | 2 | none (no money moves) |
| Block card | 3 | Fraud Analyst |
| Request customer verification | 3 | Fraud Analyst |
| **Freeze account** | **4** | **Fraud Analyst + Risk Officer** |

The approval matrix lives in `backend/src/nexa/config/approval_matrix.py`. Higher levels also expire:
a pending approval times out after 60 to 240 minutes.

## The rules that make it safe

- **Authorization is code, never an AI.** No permission logic lives in a prompt.
- **Agents never touch the bank.** They call tools, and the tools check permissions.
- **Findings are typed.** Agents pass codes to each other, never prose. Merchant names and memos
  (third-party text, where a prompt injection could hide) never reach a model.
- **The action list is closed.** The decision picks from a fixed set and cannot invent an action.
- **Scores are rankings, not probabilities.** Nobody has calibrated them, and the page says so.

## What each screen section is

| Section | It shows |
|---|---|
| **Load a scenario** (A to K) | 11 made-up test cases. Each probes something: A normal, B suspicious, C missing KYC, D conflicting evidence, E unauthorized attempt, F account takeover (two approvers), G prompt injection, H legitimate traveller, I thin history, J structured deposits, K new phone but not a takeover. |
| **Waiting on humans** | cases paused until someone votes |
| **Relay** (the nine stages) | what has happened so far. Replay or scrub it, or click a stage to filter the audit table. |
| **Evidence** | the typed findings, each tagged risk or not |
| **Recommendation** | the suggested action, risk level (1 to 5), candidate scores and the policy clauses cited |
| **Approval** | seats for each required role. You can vote here if your role is needed. |
| **Audit chain** | the sealed, ordered record of everything that happened |
| **Ask the bank** | answers from the bank's knowledge base. What you can see depends on who you are: customers see less than staff. |

## Three roles in the demo

| Token | Can do |
|---|---|
| **Analyst** | open cases, vote as Fraud Analyst |
| **Risk officer** | open cases, vote as Risk Officer |
| **Customer** | only "Ask the bank", and only customer-safe answers |

## Where to read more

`README.md` (architecture and results) · `docs/architecture.md` · `docs/decision.md` (rules and gates) ·
`docs/security-model.md` · `docs/demo.md` (the six-minute script).
