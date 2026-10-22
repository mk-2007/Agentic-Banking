# How to run it (start here)

Everything is synthetic data on one machine. No bank, no real keys needed for the core demo.

## 1. Install (once)
```powershell
cd "E:\Allied Bank Hackathon"
pip install -e "backend[dev]"
```
Needs Python 3.11+. For the browser test only: `pip install playwright` and Chrome installed.

## 2. Check the build (about 90 seconds)
```powershell
cd backend
python -m pytest -q          # 854 tests, including layer rules and the browser test
python -m ruff check .
python -m mypy
cd ..
```

## 3. Start the app (offline, no model, no cost)
```powershell
python -u scripts/run_api.py --demo
```
It prints a **username and password** for four users (`demo_analyst`, `demo_risk_officer`, `demo_auditor`,
`demo_customer`) and bearer tokens for scripts. They change every start. Open <http://127.0.0.1:8000>.
Use three windows (one normal, two private): customer, analyst, risk officer, and sign in with the printed
passwords.

| Option | Effect |
|--------|--------|
| `--llm --providers anthropic` | a model monitors and investigates (needs `ANTHROPIC_API_KEY` in `.env`; see `.env.example`) |
| `--llm-decisions` | the model also ranks actions (rules and gates still decide) |
| `--data-dir data/run` | approvals and the audit log survive a restart |
| `--no-monitor` | do not review customer payments in the background |
| `--port 8001` | another port |

Your own users instead of demo ones:
```powershell
python -c "from nexa.api.sessions import hash_password; print(hash_password('your-password'))"   # run from backend/src
$env:NEXA_API_USERS="ana:<hash>:fraud_analyst,rob:<hash>:risk_officer,aisha:<hash>:customer:cust_010"
python -u scripts/run_api.py
```

## 4. What to do in the app
1. **Customer window:** *Bank app* > *Everyday grocery* > **Pay**. The analyst's *Live feed* shows it cleared.
2. Customer: *Big transfer, new phone*, amount 9000, **Pay** about six times: the monitor opens a case.
3. **Analyst window:** *Control room* shows the case, evidence and recommendation (a freeze). Vote **approve**.
4. **Risk officer window:** vote **approve**. Two different roles are required; the freeze executes.
5. Customer pays again: refused, the account is frozen.
6. Anyone: *Ask the bank* answers from the knowledge base, filtered by who you are.
7. **Auditor window:** the evaluation lab and scorecards.

## 5. Evaluations and reports
```powershell
python scripts/run_agent_eval.py        # 7 scenarios, offline
python scripts/run_holdout_eval.py      # holdout seeds, cost, drift; writes docs/evaluation.md
python scripts/run_sim_eval.py --seeds 2 --llm --providers anthropic   # with Claude (costs tokens)
python scripts/gen_status.py            # regenerate docs/STATUS.md
```

## 6. If something is wrong
| Symptom | Fix |
|---------|-----|
| Port already in use | an earlier server is still running; stop it or use `--port 8001` |
| Passwords not printed when output is redirected | run with `python -u` |
| *wrong username or password* | demo passwords change on each start; use the new ones; 5 failures lock a user for 5 minutes |
| Model steps skipped | no key or no `--llm`; the rules still work |
| A restart lost my cases | cases and the bank's state are in memory; only approvals and audit persist with `--data-dir` |

More: `docs/RUN_AND_PRESENT.md` (presenting), `docs/STATUS.md` (current numbers), `docs/IMPROVEMENT_PLAN.md` (what is open).
