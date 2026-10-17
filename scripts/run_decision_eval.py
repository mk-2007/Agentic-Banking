"""Score the decision providers on all the scenarios and print a safe/useful report.

    python scripts/run_decision_eval.py          # rules plus stand-in models: no network, no key
    python scripts/run_decision_eval.py --live   # also score a real model through the gateway

The stand-in models misbehave on purpose (reckless, lazy, broken); each must still come out *safe*.
``--live`` reads your keys from ``.env`` and spends a few tokens per scenario. Exit code 1 means a
provider produced an unsafe recommendation.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "tests" / "evals"))

from decision_harness import format_report, run_all  # noqa: E402

from nexa.llm import LlmConfigError, UsageLedger, build_gateway, load_dotenv_file  # noqa: E402


def main() -> int:
    """Run the evaluation and return a process exit code (0 when every recommendation is safe)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="also score a real model")
    args = parser.parse_args()

    gateway = None
    ledger = UsageLedger(case_token_budget=1_000_000)
    if args.live:
        try:
            gateway = build_gateway(load_dotenv_file(ROOT / ".env"), ledger=ledger)
        except LlmConfigError as error:
            print(f"cannot run live: {error}")
            return 2
        print(f"providers: {', '.join(gateway.provider_names)}")

    outcomes = run_all(gateway)
    print(format_report(outcomes))
    if gateway is not None:
        used = ledger.summary()
        print(f"\nmodel calls: {used.calls}, tokens: {used.total_tokens}")
    return 0 if all(o.safe for o in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
