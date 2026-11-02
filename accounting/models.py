"""Account values: money and subscription quotas are distinct quantities."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple


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
