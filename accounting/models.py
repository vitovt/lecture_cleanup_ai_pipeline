"""Provider-reported account and request accounting values."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple


@dataclass(frozen=True)
class Balance:
    currency: str
    total: Decimal
    granted: Optional[Decimal] = None
    topped_up: Optional[Decimal] = None


def balance_fields(balance):
    """Only emit balance components actually supplied by the provider."""
    return {key: format(value, 'f') if isinstance(value, Decimal) else value
            for key, value in asdict(balance).items() if value is not None}


@dataclass(frozen=True)
class BalanceSnapshot:
    available: bool
    balances: Tuple[Balance, ...]


@dataclass(frozen=True)
class Quota:
    name: str
    unit: str
    used: int
    limit: int
    remaining: int
    overage: int
    resets_at: Optional[str] = None


@dataclass(frozen=True)
class AccountSnapshot:
    scope: str
    provider: str
    status: str
    checked_at: str
    reason: Optional[str] = None
    available: Optional[bool] = None
    balances: Tuple[Balance, ...] = ()
    quotas: Tuple[Quota, ...] = ()
    tier: Optional[str] = None
    subscription_status: Optional[str] = None


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TokenUsage:
    """Optional response metrics; money is only a provider-reported amount."""
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cache_hit_tokens: Optional[int] = None
    cache_miss_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    cost: Optional[Decimal] = None
    currency: Optional[str] = None
