# Run it yourself and present it (a point-by-point guide)

For the person presenting. Everything runs on one Windows laptop; the data is synthetic. Allow 10 minutes to set up
and rehearse once.

## 1. One-time setup

```powershell
cd "E:\Allied Bank Hackathon"
python -m venv backend\.venv; backend\.venv\Scripts\activate     # optional
pip install -e "backend[dev]"
pip install websockets                                           # only needed to remake the video
copy .env.example .env                                           # then edit .env (below)
```

In `.env` (git-ignored, never commit it) put each key on its own line **with its name**:

```
ANTHROPIC_API_KEY=sk-ant-...        # Claude: fast, reliable, the one to present with
GEMINI_API_KEY=...                  # optional fallback (the free tier often runs out)
GROQ_API_KEY=...                    # optional fallback
```

A bare key on a line by itself is ignored. Rotate any key that has been pasted into a chat.

Check it before you present: `$env:NEXA_LLM_PROVIDERS="anthropic"; python scripts/llm_smoke_test.py` should print
`anthropic: OK`. (If you have no key at all, every step below still works without `--llm`; the model parts are skipped.)

## 2. Start the app

| You want | Command |
|---|---|
| The safe, offline demo (no model, no cost) | `python scripts/run_api.py --demo` |
| **The agentic demo** (a model monitors and investigates; rules and gates decide) | `python scripts/run_api.py --demo --llm --providers anthropic,gemini` |
| The model also ranks the actions | add `--llm-decisions` |

It prints four sign-in tokens (analyst, risk officer, auditor, customer). They change every start. Open
<http://127.0.0.1:8000>. Use **three browser windows** (one normal, two private/incognito): customer, analyst,
risk officer. In each: paste a token, press **Plug in**.

The page asks for a token because the server, not the page, decides who you are and what you may do; the page cannot
set its own role. (See `docs/PROJECT_GUIDE.md`, part 8.)

## 3. The five-minute live demo

| # | Window | Do | Say |
|---|---|---|---|
| 1 | Customer, **Bank app** | Click *Everyday grocery*, **Pay** | "An ordinary payment from the customer's own phone. The bank decides whether the device is registered and whether the payee is new; the customer cannot set either." |
| 2 | Analyst, **Live feed** | Look at the first row | "Cleared as *routine*: no case, no model." |
| 3 | Customer | Click *Big transfer, new phone*, set **Amount to 9000**, **Pay**. **Repeat six times** (the form resets after each payment, so click the preset and set the amount each time) | "A takeover: a new phone, failed logins, six transfers to new payees." |
| 4 | Analyst, **Live feed** | Wait about a minute (a model is investigating). Rows turn *opened* / *linked*; one case waits for approval | "A policy threshold was crossed, so cases open on their own, whatever any model thinks. The burst is one case until something new appears: the fifth payment in an hour." |
| 5 | Analyst | Click the row with a case, open **Investigation** | "The model chose which records to look at. It never saw a merchant name. Each claim was checked by code against only what it looked at; it can add a finding, never remove or invent one." |
| 6 | Analyst | Show **Recommendation** (freeze account, level 4) and **Approval** | "A freeze is level four: two different roles." |
| 7 | Analyst | **approve** | "One approval is not enough. Nothing has changed." |
| 8 | Risk officer | Open the same case, **approve** | "Second role. Now, and only now, the guarded tool runs, once." |
| 9 | Customer | Press **Pay** again | "The frozen account refuses the customer's next payment." |
| 10 | Auditor, **Capability**, card 5 | Scroll to *Randomised traffic* | "The same random traffic with and without a model. Both catch the fraud; only the model recognises structuring. No honest customer was restricted." |

The model-free fallback is part of the point: if a model is slow or down, the case still completes on the baseline.
If the investigation takes long, talk through step 5 from the screenshots in `presentation/demo/shots/`.

## 4. The talk track (2 minutes) and the questions to expect

1. **What it is:** "Agents investigate; plain code enforces the rules; named humans authorize anything serious."
2. **What is new:** payments are watched live; a model chooses what to look at; code checks every claim; low-risk actions run
   on their own; high-risk ones wait for people.
3. **How we know it works:** randomised honest and fraudulent traffic, with and without a model (`docs/adr/0016`).
4. **What it is not:** two seeds on synthetic data; our personas and labels; not proof on a real bank.

| They ask | You answer |
|---|---|
| "Is the AI deciding?" | "It proposes. Authorization is plain code, approvals are single-use and bound to one action, account and case, and a model can open a case but never clear a threshold crossing." |
| "What if the model lies?" | "Each claim is checked against what it actually looked at. In our run 4 of 51 claims were dropped. It can add a finding, never remove or invent one." |
| "Prompt injection?" | "The model never sees a merchant name or memo; merchants become opaque refs. A test proves no merchant text reaches a prompt." |
| "What does the model add over rules?" | "It found structuring, which the arithmetic never searches for. Without it, structuring is escalated only by accident; the *recognised* measure shows the difference (6 of 8 versus 8 of 8)." |
| "Is it accurate?" | "We do not claim that. Two seeds, a synthetic bank, our own labels." |
| "Why a token on the page?" | "The server decides identity and role; the page cannot lie about who you are." |
| "What if the model is down?" | "A failed model opens the case rather than guess; the baseline analysis stands alone." |

## 5. Other things you can run

```powershell
cd backend
pytest -q                          # 838 tests, including the architecture rules
ruff check . ; ruff format --check . ; mypy
cd ..
python scripts/run_sim_eval.py                                   # randomised traffic, no model (seconds)
python scripts/run_sim_eval.py --seeds 2 --llm --providers anthropic   # the same with Claude (about 5 minutes)
python scripts/run_demo.py                                       # the scripted API demo with pass/fail checks
```

## 6. Remake the video

```powershell
python scripts/make_demo_video.py all --providers anthropic,gemini
```

`record` plays the whole story through a real headless Chrome against the server with a model on (the screens are the real
ones), `narrate` speaks the script with Windows' built-in voice, `assemble` renders a captioned `.webm` in Chrome. Output:
`presentation/demo/nexa-agentic-demo.webm` (about 2 minutes). Edit the words in `SCENES` at the top of the script. The
folder is git-ignored by default because the video is about 30 MB.

## 7. If something goes wrong

| Symptom | Fix |
|---|---|
| *missing or unknown token* | Tokens change every start; paste the new ones. |
| Customer sees only "Ask the bank" | That token is not linked to a bank customer; use the printed customer token. |
| Live feed shows *model unavailable* | The key is missing, wrong, or out of quota. The cases still complete on the baseline; run the smoke test above. |
| Nothing waits for approval | Make sure the amount was 9000 and the preset was clicked before **each** of the six payments. |
| Slow cases | A free-tier model rate-limits; use Claude (`--providers anthropic`). |
| Port 8000 busy | `python scripts/run_api.py --demo --llm --port 8010`. |
