"""Write docs/STATUS.md from facts (test count, phase status, latest evaluation, release tag).

Run after a change: ``python scripts/gen_status.py``. It is the one place with current numbers;
other documents link to it, and a test fails if the README quotes a different test count.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*cmd: str, cwd: Path = ROOT) -> str:
    """Return the stdout of a command."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def main() -> None:
    """Collect the facts and write the page."""
    collected = run(sys.executable, "-m", "pytest", "--collect-only", "-q", cwd=ROOT / "backend")
    tests = next(
        line.split()[0] for line in reversed(collected.splitlines()) if "collected" in line or "tests" in line
    )
    graph = json.loads((ROOT / "docs/context/graph.json").read_text(encoding="utf-8"))
    phases = [n for n in graph["nodes"] if n["id"].startswith("phase:")]
    adrs = len(list((ROOT / "docs/adr").glob("0*.md")))
    tag = run("git", "describe", "--tags", "--abbrev=0")
    head = run("git", "rev-parse", "--short", "HEAD")
    sim = json.loads((ROOT / "data/lab_results/sim.json").read_text(encoding="utf-8"))
    rows = "\n".join(f"| {n['id']} | {n['status']} | {n.get('summary', '')} |" for n in phases)
    page = f"""# Status (generated; do not edit)

Regenerate with `python scripts/gen_status.py`. Other documents link here for current numbers.

- **Tests:** {tests} collected
- **Architecture decision records:** {adrs}
- **Latest release tag:** {tag}; built from commit {head}
- **Latest randomised-traffic run:** saved {sim.get("saved_at")}, provider {sim.get("provider")}, \
{sim.get("seeds")} seeds, {sim.get("seconds")} s

| Phase | Status | Summary |
|-------|--------|---------|
{rows}

Open work is in [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md).
"""
    (ROOT / "docs/STATUS.md").write_text(page, encoding="utf-8", newline="\n")
    print(f"wrote docs/STATUS.md ({tests} tests)")


if __name__ == "__main__":
    main()
