"""Provider-neutral currency balances shared by account checks and adapters."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple


@dataclass(frozen=True)
class Balance:
    currency: str
    total: Decimal
    granted: Decimal
    topped_up: Decimal


@dataclass(frozen=True)
class BalanceSnapshot:
    available: bool
    balances: Tuple[Balance, ...]
