"""The README may not quote a test count that disagrees with the generated status page."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_readme_test_count_matches_status_page() -> None:
    status = (ROOT / "docs/STATUS.md").read_text(encoding="utf-8")
    actual = re.search(r"\*\*Tests:\*\* (\d+)", status)
    assert actual, "run python scripts/gen_status.py"
    quoted = set(re.findall(r"(\d+) tests", (ROOT / "README.md").read_text(encoding="utf-8")))
    assert quoted <= {actual.group(1)}, f"README says {quoted}, STATUS says {actual.group(1)}"
