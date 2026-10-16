"""Run one scenario (or all of them) through the case graph and show what happened.

    python scripts/run_case.py scenario_b_suspicious
    python scripts/run_case.py --all

Offline: no model, no network, no key. Run it from the repository root with the package installed
(``pip install -e backend``) or with ``PYTHONPATH=backend/src``.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "tests" / "support"))

from agent_world import SCENARIOS, build_world  # noqa: E402

from nexa.agents import code_of, signal_of  # noqa: E402
from nexa.orchestration import CaseRun, run_case  # noqa: E402


def show(scenario_id: str) -> CaseRun:
    """Run ``scenario_id`` and print its journey."""
    world = build_world()
    run = run_case(world.case(scenario_id), world.context())
    print(f"\n{scenario_id}  ({SCENARIOS[scenario_id].title})")
    print("  path:    " + " -> ".join(s.value for s in run.trail))
    print(f"  result:  {run.case.status.value}" + (f"  [{run.failure}]" if run.failure else ""))
    if run.investigation:
        inv = run.investigation
        for finding in inv.findings:
            signal, code = signal_of(finding), code_of(finding)
            print(f"  {signal.value if signal else '?':<10} {code.value if code else '?':<22} {finding.summary}")
        flags = ", ".join(f.value for f in inv.verification.uncertainty_flags) or "none"
        refs = ", ".join(f"{r.doc_id}#{r.section or 'all'}" for r in inv.policy.policy_refs) or "none"
        print(f"  flags:   {flags}")
        print(f"  policy:  {refs}")
        print(f"  evidence recorded on the case: {len(run.case.evidence_ids)}")
    return run


def main() -> int:
    """Return 0 when every run reached a decision-ready case."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario", nargs="?", help="scenario id, for example scenario_b_suspicious")
    parser.add_argument("--all", action="store_true", help="run all seven scenarios")
    args = parser.parse_args()
    if not args.all and args.scenario not in SCENARIOS:
        print("choose one of:\n  " + "\n  ".join(SCENARIOS) + "\nor use --all")
        return 2
    ids = list(SCENARIOS) if args.all else [args.scenario]
    runs = [show(sid) for sid in ids]
    ready = sum(r.ready_for_decision for r in runs)
    print(f"\n{ready}/{len(runs)} cases reached decision_ready")
    return 0 if ready == len(runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
