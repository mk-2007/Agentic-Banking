"""Run a real model against the rules on the lab cases and save the comparison.

    python scripts/run_lab_live.py              # every lab case (about 100 model calls)
    python scripts/run_lab_live.py --limit 20   # a quick try

Needs at least one API key in .env or the environment (see .env.example). Keys are read, never printed
or saved. The model only proposes; the shared gates decide, and the rules take over if the model is
down or answers badly. The result is saved to data/lab_results/live.json, which the auditor's
Capability tab shows. Exit code 1 means a recommendation came out unsafe.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from nexa.api.lab import LabService, live_results_path  # noqa: E402
from nexa.domain.clock import utc_now  # noqa: E402
from nexa.evaluation import compare_live  # noqa: E402
from nexa.llm import LlmConfigError, build_gateway, load_dotenv_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None, help="only the first N lab cases")
    args = parser.parse_args()
    env = {**load_dotenv_file(ROOT / ".env"), **os.environ}
    try:
        gateway = build_gateway(env)
    except LlmConfigError as error:
        print(f"cannot use a model: {error}")
        return 2
    providers = ", ".join(gateway.provider_names)
    print(f"model providers: {providers}")
    lab = LabService()
    runs = lab.finished_runs()
    print(f"scoring {args.limit or len(runs)} of {len(runs)} lab cases (the model proposes; the gates decide)...")
    summary = compare_live(runs, gateway, utc_now, provider_label=providers, limit=args.limit)
    data = summary.as_dict()
    data["saved_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    path = live_results_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"{summary.total} cases in {summary.seconds}s: agree with rules {summary.agree}, safe {summary.safe}, "
        f"useful {summary.useful}, preferred {summary.preferred}, gate interventions {summary.gate_interventions}, "
        f"fell back to rules {summary.fallbacks}"
    )
    print(f"saved {path}")
    return 0 if summary.safe == summary.total else 1


if __name__ == "__main__":
    raise SystemExit(main())
