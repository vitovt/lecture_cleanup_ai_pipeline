"""Stable console records for LLM accounting; never persists telemetry."""

from contextlib import contextmanager
from urllib.parse import quote

from aiadapters.accounting import TokenUsage
from scripts.logging_helper import log_info


def provider_name(adapter):
    return adapter.name() if callable(getattr(adapter, "name", None)) else "unknown"


def record(event, *, emit=log_info, **fields):
    """Whitespace-separated key=value fields; values use URL percent encoding."""
    values = " ".join(f"{key}={quote(str(value), safe='-._~')}" for key, value in fields.items())
    emit(f"{event} {values}")


def report_balance(adapter, phase, *, emit=log_info):
    provider = provider_name(adapter)
    if not getattr(adapter, "supports_balance", False):
        record("LLM_BALANCE", emit=emit, provider=provider, phase=phase, status="unsupported")
        return "unsupported"
    try:
        snapshot = adapter.get_balance()
        for balance in snapshot.balances:
            record("LLM_BALANCE", emit=emit, provider=provider, phase=phase, status="ok",
                   currency=balance.currency, total=format(balance.total, "f"),
                   granted=format(balance.granted, "f"), topped_up=format(balance.topped_up, "f"),
                   available=str(snapshot.available).lower())
        return "ok"
    except Exception:
        record("LLM_BALANCE", emit=emit, provider=provider, phase=phase, status="error",
               reason="balance_unavailable")
        return "error"


@contextmanager
def balance_session(adapter):
    """Monitoring failures never prevent generation or mask its errors."""
    report_balance(adapter, "before")
    try:
        yield
    finally:
        report_balance(adapter, "after")


def generate_with_usage(adapter, messages, *, stage, usage_context=None, **options):
    # Reset before every attempt so a failed request cannot reuse previous usage.
    adapter.last_usage = None
    outcome = "error"
    try:
        result = adapter.generate(messages, **options)
        outcome = "ok"
        return result
    finally:
        usage = adapter.last_usage
        status = "unsupported" if not getattr(adapter, "supports_usage", False) else (
            "ok" if isinstance(usage, TokenUsage) else "unknown")
        fields = dict(provider=provider_name(adapter), model=options.get("model") or "unknown",
                      stage=stage, label=options.get("label") or "none", status=status,
                      outcome=outcome)
        context = usage_context or {}
        for key in ("part", "parts", "attempt", "attempts", "summary"):
            fields[key] = context.get(key, "none")
        for key in TokenUsage.__dataclass_fields__:
            value = getattr(usage, key) if isinstance(usage, TokenUsage) else None
            fields[key] = value if value is not None else "unknown"
        record("LLM_USAGE", **fields)
