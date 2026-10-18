"""Start the HTTP API.

    python scripts/run_api.py --demo            # random demo tokens, printed once at start-up
    NEXA_API_TOKENS="tok1:ana:fraud_analyst,tok2:rob:risk_officer,tok3:ayesha:customer:cust_010" \
        python scripts/run_api.py                # your own tokens (never put them in the repo)
    python scripts/run_api.py --demo --llm      # model investigates and decides (rules as fallback)

Everything is in memory: restarting forgets cases, approvals and the audit log, and the demo tokens
change. Run it from the repository root with ``pip install -e backend`` done. Interactive docs are
served at /docs.
"""

import argparse
import os
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from nexa.agents.monitor_agent import MonitorAgent  # noqa: E402
from nexa.api import CaseService, Monitor, create_app, demo_tokens, parse_tokens  # noqa: E402
from nexa.api.principals import describe  # noqa: E402
from nexa.config import DEFAULT_THRESHOLDS  # noqa: E402
from nexa.decision import LlmDecisionProvider, RuleBasedDecisionProvider  # noqa: E402
from nexa.domain.clock import utc_now  # noqa: E402
from nexa.llm import LlmConfigError, build_gateway, load_dotenv_file  # noqa: E402


def main() -> int:
    """Build the service and serve it. Returns a non-zero code when it cannot start."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="create random demo tokens")
    parser.add_argument("--llm", action="store_true", help="use the LLM decision provider")
    parser.add_argument("--no-monitor", action="store_true", help="do not review customer payments")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.demo:
        tokens = demo_tokens()
        print("demo sign-ins (shown once; send as 'Authorization: Bearer <token>'):")
        for token, who in tokens.items():
            print(f"  {who.user_id:18} {who.role.value:18} {token}")
    else:
        try:
            tokens = parse_tokens(os.environ.get("NEXA_API_TOKENS", ""))
        except ValueError as error:
            print(f"NEXA_API_TOKENS is invalid: {error}")
            return 2
        if not tokens:
            print("no tokens: set NEXA_API_TOKENS or pass --demo")
            return 2
        print(f"sign-ins: {describe(tokens)}")

    provider = None
    gateway = None
    if args.llm:
        try:
            gateway = build_gateway(load_dotenv_file(ROOT / ".env"))
        except LlmConfigError as error:
            print(f"cannot use the LLM: {error}")
            return 2
        provider = LlmDecisionProvider(gateway, utc_now, RuleBasedDecisionProvider(utc_now))
        print(f"decision provider: llm ({', '.join(gateway.provider_names)}), rules as fallback")
    else:
        print("decision provider: rules")

    service = CaseService(provider=provider, gateway=gateway)
    monitor = None
    if not args.no_monitor:
        agent = MonitorAgent(gateway, DEFAULT_THRESHOLDS)
        monitor = Monitor(service.bank, service, agent)
        print("monitor: on (every customer payment is reviewed in the background)")
    uvicorn.run(
        create_app(service, tokens, monitor=monitor), host=args.host, port=args.port, log_level="info"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
