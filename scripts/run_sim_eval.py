"""Run randomised, labelled traffic through the platform and save how it did.

    python scripts/run_sim_eval.py                       # rules only (no model, a few seconds)
    python scripts/run_sim_eval.py --seeds 2 --llm       # also with a real model in the loop (slow)
    python scripts/run_sim_eval.py --llm --llm-decisions # the model also ranks the actions

Each seed runs every persona (honest shoppers, an account takeover, card testing, structuring...)
on a fresh simulated bank, posts the payments the way the customer app does, lets the monitor open
cases, and judges what the platform recommended against the persona's label. The same seeds run
without a model (the baseline) and, with ``--llm``, with the model in the monitor and the
investigator, so the two can be compared on identical traffic. The result is saved to
``data/lab_results/sim.json``, which the auditor's Capability tab reads: the server never calls a
model for it. A real model on a free tier takes minutes per episode.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from nexa.api.sim import SimulationRunner, run_simulation  # noqa: E402
from nexa.evaluation import PERSONAS  # noqa: E402
from nexa.config.llm import LlmLimits  # noqa: E402
from nexa.llm import LlmConfigError, build_gateway, load_dotenv_file  # noqa: E402

OUT = ROOT / "data" / "lab_results" / "sim.json"
PATIENT = LlmLimits(max_attempts_per_provider=5, max_backoff_seconds=70.0, case_token_budget=120_000)


def save(doc: dict) -> None:  # type: ignore[type-arg]
    """Write the results so far; a long run keeps what it has finished."""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def main() -> int:
    """Run the simulation and save it. Returns a non-zero code when it cannot start."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=3, help="how many seeds (1..N) per persona")
    parser.add_argument("--personas", nargs="*", default=list(PERSONAS), choices=list(PERSONAS))
    parser.add_argument("--llm", action="store_true", help="also run with a real model")
    parser.add_argument("--llm-decisions", action="store_true", help="the model ranks actions too")
    parser.add_argument("--providers", default=None, help="e.g. groq,gemini (default: the .env order)")
    args = parser.parse_args()
    seeds = list(range(1, args.seeds + 1))
    personas = tuple(args.personas)

    doc: dict = {  # type: ignore[type-arg]
        "saved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seeds": seeds,
        "personas": list(personas),
        "complete": False,
        "rules": None,
        "agentic": None,
        "provider": None,
    }

    def report(tag: str):  # type: ignore[no-untyped-def]
        def show(r) -> None:  # type: ignore[no-untyped-def]
            s = r.score
            print(
                f"[{tag}] {r.persona:20} seed {r.seed}: cases={len(r.cases)} worst={s.worst} "
                f"safe={s.safe} useful={s.useful} recognised={s.recognised} ({r.seconds}s)",
                flush=True,
            )

        return show

    started = time.time()
    print("rules (no model):", flush=True)
    doc["rules"] = run_simulation(SimulationRunner(), seeds, personas, report("rules"))
    save(doc)

    if args.llm:
        env = load_dotenv_file(ROOT / ".env")
        if args.providers:
            env["NEXA_LLM_PROVIDERS"] = args.providers
        try:
            # free tiers rate-limit by the minute: wait longer and try more before giving up
            gateway = build_gateway(env, limits=PATIENT)
        except LlmConfigError as error:
            print(f"cannot use a model: {error}")
            return 2
        doc["provider"] = ", ".join(gateway.provider_names)
        print(f"agentic ({doc['provider']}):", flush=True)
        runner = SimulationRunner(gateway, llm_decisions=args.llm_decisions)
        partial: list = []  # type: ignore[type-arg]

        def keep(r) -> None:  # type: ignore[no-untyped-def]
            report("agentic")(r)
            partial.append(r)
            doc["agentic"] = {"partial": True, "episodes_done": len(partial)}
            save(doc)

        doc["agentic"] = run_simulation(runner, seeds, personas, keep)
        doc["llm_decisions"] = args.llm_decisions
    doc["complete"] = True
    doc["seconds"] = round(time.time() - started)
    save(doc)
    for mode in ("rules", "agentic"):
        if doc[mode] and "summary" in doc[mode]:
            s = doc[mode]["summary"]
            print(
                f"{mode}: fraud caught {s['fraud_caught']}/{s['fraud_episodes']} (recognised "
                f"{s['fraud_recognised']}), honest opened "
                f"{s['honest_opened']}/{s['honest_episodes']}, honest restricted "
                f"{s['honest_restricted']}, over-restricted {s['over_restricted']}"
            )
    print(f"saved {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
