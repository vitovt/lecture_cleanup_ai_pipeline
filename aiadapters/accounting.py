"""Provider-neutral, in-memory usage and balance values. No pricing assumptions."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_hit_tokens: Optional[int] = None
    cache_miss_tokens: Optional[int] = None
    # A subset of output_tokens, never an additional charge/count.
    reasoning_tokens: Optional[int] = None


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
