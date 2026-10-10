"""Simulated banking APIs (customer, account, transaction, KYC) and seed data.

Why: Stands in for a real bank behind the same interface, so production can swap it for a
gateway (PRD section 17).

Where it sits: Layer 1. Only tools may call it; agents never do.

Modules:
    models     bank-side records (customer, account, transaction, KYC)
    gateway    Protocol interfaces a real bank integration would implement
    in_memory  deterministic simulator implementing those interfaces
    scenarios  predefined evaluation scenarios A-E (+F, X) as data
    seed       loads the committed synthetic dataset
"""

from .errors import DuplicateRecordError, RecordNotFoundError
from .gateway import BankGateway
from .in_memory import InMemoryBank
from .seed import default_data_dir, load_bank, load_scenarios

__all__ = [
    "BankGateway",
    "DuplicateRecordError",
    "InMemoryBank",
    "RecordNotFoundError",
    "default_data_dir",
    "load_bank",
    "load_scenarios",
]
