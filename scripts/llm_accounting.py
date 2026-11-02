"""Stable console records for LLM accounting; never persists telemetry."""

from contextlib import contextmanager
import logging

from accounting.usage import format_record, report_usage, usage_session
from scripts.logging_helper import log_info


def provider_name(adapter):
    return adapter.name() if callable(getattr(adapter, "name", None)) else "unknown"


def record(event, *, emit=log_info, **fields):
    """Whitespace-separated key=value fields; values use URL percent encoding."""
    emit(format_record(event, **fields))


def report_balance(adapter, phase, *, emit=log_info):
    provider = provider_name(adapter)
    if not getattr(adapter, "supports_balance", False):
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
    with usage_session(emit=log_info):
        try:
            yield
        finally:
            report_balance(adapter, "after")


def generate_with_usage(adapter, messages, *, stage, usage_context=None, **options):
    # Reset before every attempt so a failed request cannot reuse previous usage.
    adapter.last_usage = None
    adapter._request_usages = []
    outcome = "error"
    try:
        result = adapter.generate(messages, **options)
        outcome = "ok"
        return result
    finally:
        context = {key: value for key, value in (usage_context or {}).items()
                   if key in ("part", "parts", "attempt", "attempts", "summary")}
        context["label"] = options.get("label")
        responses = getattr(adapter, "_request_usages", []) or [adapter.last_usage]
        for usage in responses:
            report_usage(usage, scope="cleanup", provider=provider_name(adapter),
                         model=options.get("model") or adapter.model or "unknown", stage=stage,
                         emit=log_info, record=record, outcome=outcome,
                         visible=logging.getLogger("lecture_pipeline").isEnabledFor(logging.INFO),
                         **context)
