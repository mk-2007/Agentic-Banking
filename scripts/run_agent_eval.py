"""Run the specialist agents on the seven scenarios and print a pass/fail report.

    python scripts/run_agent_eval.py          # deterministic: no model, no network, no key
    python scripts/run_agent_eval.py --live   # let a real model narrow the policy clauses

Run it from the repository root with ``NEXA`` installed (``pip install -e backend``) or with
``PYTHONPATH=backend/src``. ``--live`` reads your keys from ``.env`` and uses the gateway, so it
spends a few tokens per scenario; keys are never printed.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "tests" / "evals"))

from harness import format_report, run_all  # noqa: E402

from nexa.llm import LlmConfigError, UsageLedger, build_gateway, load_dotenv_file  # noqa: E402


def main() -> int:
    """Run the evaluation and return a process exit code (0 when every scenario passes)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="use a real model in the policy step")
    args = parser.parse_args()

    gateway = None
    ledger = UsageLedger(case_token_budget=1_000_000)
    if args.live:
        try:
            gateway = build_gateway(load_dotenv_file(ROOT / ".env"), ledger=ledger)
        except LlmConfigError as error:
            print(f"cannot run live: {error}")
            return 2
        print(f"providers: {', '.join(gateway.provider_names)}\n")

    results = run_all(gateway)
    print(format_report(results))
    if gateway is not None:
        used = ledger.summary()
        print(f"model calls: {used.calls}, tokens: {used.total_tokens}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
