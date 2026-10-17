"""The demo script is a living check: it drives the real API and fails if any expectation breaks."""

import runpy
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "run_demo.py"


def test_demo_script_passes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["run_demo.py", "--write", str(tmp_path / "report.md")])
    with pytest.raises(SystemExit) as done:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert done.value.code == 0
    assert "FAIL" not in (tmp_path / "report.md").read_text(encoding="utf-8")
