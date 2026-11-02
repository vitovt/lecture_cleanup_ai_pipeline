"""Provider-neutral, in-memory usage and balance values. No pricing assumptions."""

from dataclasses import dataclass
from typing import Optional

# Compatibility exports for existing adapters and telemetry consumers.
from accounting.models import Balance, BalanceSnapshot


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_hit_tokens: Optional[int] = None
    cache_miss_tokens: Optional[int] = None
    # A subset of output_tokens, never an additional charge/count.
    reasoning_tokens: Optional[int] = None
