"""Load the synthetic dataset from ``data/synthetic/`` into the simulated bank.

The JSON files are produced by ``scripts/generate_synthetic_data.py`` and committed, so
every run, test and demo sees exactly the same bank.
"""

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .in_memory import InMemoryBank
from .models import AccountRecord, CustomerRecord, KycRecord, TransactionRecord
from .scenarios import ScenarioSpec


def default_data_dir() -> Path:
    """Return ``data/synthetic`` for a normal checkout of the repository."""
    return Path(__file__).resolve().parents[4] / "data" / "synthetic"


_M = TypeVar("_M", bound=BaseModel)


def _read(directory: Path, filename: str, model: type[_M]) -> list[_M]:
    """Read a JSON array file and validate every element as ``model``."""
    raw = json.loads((directory / filename).read_text(encoding="utf-8"))
    return [model.model_validate(item) for item in raw]


def load_bank(data_dir: Path | None = None) -> InMemoryBank:
    """Build a simulated bank from the synthetic JSON files."""
    directory = data_dir or default_data_dir()
    return InMemoryBank(
        customers=_read(directory, "customers.json", CustomerRecord),
        accounts=_read(directory, "accounts.json", AccountRecord),
        transactions=_read(directory, "transactions.json", TransactionRecord),
        kyc=_read(directory, "kyc.json", KycRecord),
    )


def load_scenarios(data_dir: Path | None = None) -> tuple[ScenarioSpec, ...]:
    """Load the predefined evaluation scenarios."""
    directory = data_dir or default_data_dir()
    return tuple(_read(directory, "scenarios.json", ScenarioSpec))
