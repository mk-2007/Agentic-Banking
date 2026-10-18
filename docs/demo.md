# Demo script (about 6 minutes)

Audience: judges. Message: **agents recommend, code enforces, humans authorize.** Everything is synthetic and
offline unless you pass `--llm`. A recorded run of the same flow is in [demo-report.md](demo-report.md); regenerate it
with `python scripts/run_demo.py --write docs/demo-report.md`.

## Setup (once)

```
python -m pip install -e "backend[dev]"
python scripts/run_api.py --demo            # prints three tokens: analyst, risk officer, customer
```

Open <http://127.0.0.1:8000>. Use two browser windows (or one window and a private window) so two people can be
signed in at once: paste the **analyst** token in one and the **risk officer** token in the other, click Connect.

## Walkthrough

| # | Do | Say | Point at |
|---|---|---|---|
| 1 | Open **Normal transaction** | "A routine purchase. The system does nothing, and says why." | Level 1, no approval, findings |
| 2 | Open **Suspicious transaction** | "Card testing then a large foreign purchase. It recommends blocking the card." | Typed findings (codes, not prose); policy references; Level 3 needs one human |
| 3 | Open **Conflicting evidence** | "Signals disagree. It does not guess: it flags the conflict and asks a person." | `conflicting_evidence` flag, human floor |
| 4 | Open **Prompt injection** | "The memo tells the AI to freeze an account. It never reaches a prompt or this screen." | Nothing from the memo is shown; action is only monitoring |
| 5 | Open **Account takeover** | "The most severe action: freezing an account. Level 4 needs two different roles." | Required roles, expiry, status *waiting for approval* |
| 6 | In the analyst window click **approve** | "One approval is not enough; nothing has changed." | Still waiting; one vote listed |
| 7 | Click **approve** again as the analyst | "The same role twice does not count as two." | Still waiting |
| 8 | In the risk officer window open the case, click **approve** | "Second role. Now, and only now, the guarded tool runs." | Status *completed*; audit shows `action_executed` |
| 9 | Click approve once more | "A replay is refused." | Error: not waiting |
| 10 | Scroll the audit chain | "Every step is hash-chained; editing the log is detectable." | Event hashes |
| 11 | Optional: `curl` the API with the customer token | "A customer can only ask the knowledge base." | 403 on `/cases` |

## Live demo (agentic mode, about 5 minutes)

Start `python scripts/run_api.py --demo --llm` (a key in `.env`; set `NEXA_LLM_PROVIDERS=anthropic` to use Claude
for the final run). It prints four tokens. Use three windows: customer,
analyst, risk officer.

| # | Do | Say | Point at |
|---|---|---|---|
| 1 | Customer window, **Bank app**: click *Everyday grocery*, **Pay** | "An ordinary payment from the customer's own phone." | Balance drops; no case is opened |
| 2 | Analyst window, **Live feed** | "The monitor reviewed it and cleared it: routine, no model, no case." | `cleared` / `routine` |
| 3 | Customer: click *Big transfer, new phone*, **Pay** | "A new device, failed logins, a new payee. The bank works out the device and payee itself; the customer cannot set them." | The two *simulate* fields are labelled as the bank's sensors |
| 4 | Analyst, Live feed | "A policy threshold was crossed, so a case opens whatever any model thinks. A model investigates it." | `opened` / `floor`; click the row |
| 5 | In the case, show the **investigation** and findings | "The model chose which records to look at. It never saw a merchant name. Each claim was checked against what it actually looked at." | Lookups, claimed / confirmed / dropped |
| 6 | Auditor window, **Capability**, card 5 | "The same random seeds, with and without a model. Structuring is escalated by accident without one and recognised with one." | caught vs **recognised**; honest restricted = 0 |
| 7 | Takeover: the *Account takeover* scenario (control room) | "Level 4: two roles must approve; one is not enough." | Waiting for approval, two roles |
| 8 | Customer window after approval | "The frozen account now refuses the customer's next payment." | 409 *account is frozen* |

## If something goes wrong

- Page says *missing or unknown token*: demo tokens change every start; paste the new ones.
- Case stays *waiting*: the approval window is 240 minutes for Level 4 in config; use a fresh case.
- Live model unavailable (`--llm`): the rule-based provider takes over by design; say so, it is the point.
- Never pass real data. The dataset is synthetic.

## Honest limits to say out loud

Static tokens in memory, state lost on restart, rules written for the first seven scenarios, live model scored on seven
cases only (see [decision-comparison.md](decision-comparison.md) and [api.md](api.md)).
