"""Shared response metrics, request reporting and totals for LLM and STT.

No SDK, credential, network, pricing-table or application-logger dependency.
"""
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation
import json
import os
from urllib.parse import quote

from .models import TokenUsage

EVENT_FILE = 'LECTURE_USAGE_EVENTS'
_SESSION = ContextVar('lecture_usage_session', default=None)
_CONTEXT = ContextVar('lecture_usage_context', default={})
TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'total_tokens', 'cache_hit_tokens',
                'cache_miss_tokens', 'reasoning_tokens')


def response_json(data):
    """Decode JSON with exact monetary decimals; saved costs use decimal strings."""
    def native(value, key=None):
        if isinstance(value, Decimal):
            return format(value, 'f') if key == 'cost' else float(value)
        if isinstance(value, dict):
            return {name: native(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [native(item) for item in value]
        return value
    return native(json.loads(data, parse_float=Decimal))


def field(value, key):
    try:
        return value.get(key) if isinstance(value, dict) else getattr(value, key, None)
    except Exception:
        return None  # Optional SDK metadata must not prevent text/audio processing.


def count(value):
    return value if type(value) is int and value >= 0 else None


def amount(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def normalize_usage(response, *, currency=None):
    """Normalize common response protocols, keeping tokens and money independent.

    Currency must be explicit in usage or declared by the API integration.
    Never interpret token prices or upstream/BYOK estimates as a request charge.
    """
    usage = field(response, 'usage')
    google = False
    if usage is None:
        usage = field(response, 'usage_metadata') or field(response, 'usageMetadata')
        google = usage is not None
    if usage is None:
        wrapped = field(response, 'data')
        return normalize_usage(wrapped, currency=currency) if isinstance(wrapped, dict) else None
    if google:
        def metric(snake, camel):
            value = field(usage, snake)
            return count(field(usage, camel) if value is None else value)
        inputs = metric('prompt_token_count', 'promptTokenCount')
        outputs = metric('candidates_token_count', 'candidatesTokenCount')
        total = metric('total_token_count', 'totalTokenCount')
        reasoning = metric('thoughts_token_count', 'thoughtsTokenCount')
        if outputs is not None and reasoning is not None:
            outputs += reasoning
        tool_inputs = metric('tool_use_prompt_token_count', 'toolUsePromptTokenCount')
        if inputs is not None and tool_inputs is not None:
            inputs += tool_inputs
        cached = metric('cached_content_token_count', 'cachedContentTokenCount')
        missed = None
    else:
        responses = field(usage, 'input_tokens') is not None or field(usage, 'output_tokens') is not None
        inputs = count(field(usage, 'input_tokens' if responses else 'prompt_tokens'))
        outputs = count(field(usage, 'output_tokens' if responses else 'completion_tokens'))
        total = count(field(usage, 'total_tokens'))
        input_details = field(usage, 'input_tokens_details' if responses else 'prompt_tokens_details')
        output_details = field(usage, 'output_tokens_details' if responses else 'completion_tokens_details')
        cached = count(field(input_details, 'cached_tokens'))
        if cached is None:
            cached = count(field(usage, 'prompt_cache_hit_tokens'))
        missed = count(field(usage, 'prompt_cache_miss_tokens'))
        reasoning = count(field(output_details, 'reasoning_tokens'))
        # Reject inconsistent/invalid core blocks, without losing a valid charge.
        core_keys = ('input_tokens', 'output_tokens', 'total_tokens') if responses else ('prompt_tokens', 'completion_tokens', 'total_tokens')
        if any(field(usage, key) is not None and count(field(usage, key)) is None for key in core_keys):
            inputs = outputs = total = None
    if inputs is not None and outputs is not None and total is not None and total != inputs + outputs:
        inputs = outputs = total = None
    if inputs is None:
        cached = missed = None
    elif cached is not None and (cached > inputs or (missed is not None and cached + missed != inputs)):
        cached = missed = None
    elif cached is not None:
        missed = inputs - cached
    elif missed is not None and missed > inputs:
        missed = None
    if outputs is None or (reasoning is not None and reasoning > outputs):
        reasoning = None
    code = field(usage, 'currency') or currency
    if not isinstance(code, str) or len(code) != 3 or not code.isascii() or not code.isalpha():
        code = None
    cost = amount(field(usage, 'cost')) if code else None
    result = TokenUsage(inputs, outputs, total, cached, missed, reasoning, cost,
                        code.upper() if cost is not None else None)
    return result if metrics(result) else None


def metrics(usage):
    if not isinstance(usage, TokenUsage):
        return {}
    result = {key: value for key in TOKEN_FIELDS if (value := count(getattr(usage, key))) is not None}
    cost = amount(usage.cost)
    if cost is not None and usage.currency:
        result.update(cost=format(cost, 'f'), currency=usage.currency)
    return result


def format_record(event, **fields):
    return event + ' ' + ' '.join(f'{key}={quote(str(value), safe="-._~")}' for key, value in fields.items() if value is not None)


class UsageTotals:
    def __init__(self):
        self.events = []

    def add(self, event):
        if (isinstance(event, dict) and isinstance(event.get('metrics'), dict) and
            all(isinstance(event.get(key), str) for key in ('scope', 'provider', 'model'))):
            self.events.append(event)

    def records(self):
        groups = defaultdict(list)
        for event in self.events:
            groups[(event['scope'], event['provider'], event['model'])].append(event)
        if len(groups) > 1:
            groups[('all', 'all', 'all')] = list(self.events)
        for (scope, provider, model), events in groups.items():
            sums = {}
            for key in TOKEN_FIELDS:
                values = [e['metrics'][key] for e in events if count(e['metrics'].get(key)) is not None]
                if values:
                    sums[key] = sum(values)
                    if len(values) < len(events):
                        sums[f'{key}_requests'] = len(values)
                        sums['partial'] = 'true'
            currencies = sorted({e['metrics']['currency'] for e in events if 'cost' in e['metrics']})
            costs = []
            for currency in currencies:
                values = [Decimal(e['metrics']['cost']) for e in events if e['metrics'].get('currency') == currency]
                row = dict(cost=format(sum(values, Decimal(0)), 'f'), currency=currency)
                if len(values) < len(events):
                    row.update(cost_requests=len(values), partial='true')
                costs.append(row)
            if sums or costs:
                base = dict(scope=scope, provider=provider, model=model, requests=len(events), **sums)
                yield {**base, **(costs[0] if len(costs) == 1 else {})}
                if len(costs) > 1:
                    for row in costs:
                        yield dict(scope=scope, provider=provider, model=model, requests=len(events), **row)


def report_usage(usage, *, scope, provider, model, stage, emit, record=None,
                 visible=True, outcome='ok', **context):
    """One call per actual API attempt, even when no statistics were returned."""
    values = metrics(usage)
    event = dict(scope=scope, provider=provider, model=model, metrics=values, visible=visible)
    session = _SESSION.get()
    if session is not None:
        session.add(event)
    journal = os.environ.get(EVENT_FILE)
    if journal:
        try:
            data = (json.dumps(event, separators=(',', ':')) + '\n').encode()
            descriptor = os.open(journal, os.O_WRONLY | os.O_APPEND)
            try:
                os.write(descriptor, data)
            finally:
                os.close(descriptor)
        except OSError:
            pass  # Monitoring must never fail a paid request or hide its error.
    if values and visible:
        fields = {**dict(scope=scope, provider=provider, model=model, stage=stage,
                         status='ok', outcome=outcome), **_CONTEXT.get(), **context, **values}
        if record is not None:
            record('LLM_USAGE' if scope == 'cleanup' else 'STT_USAGE', **fields)
        else:
            emit(format_record('LLM_USAGE' if scope == 'cleanup' else 'STT_USAGE', **fields))


@contextmanager
def usage_context(**context):
    token = _CONTEXT.set({**_CONTEXT.get(), **context})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


@contextmanager
def usage_session(*, emit):
    """Standalone totals; an enclosing workflow journal owns combined totals."""
    if _SESSION.get() is not None or os.environ.get(EVENT_FILE):
        yield
        return
    totals = UsageTotals()
    token = _SESSION.set(totals)
    try:
        yield
    finally:
        _SESSION.reset(token)
        if any(event['visible'] for event in totals.events):
            for fields in totals.records():
                emit(format_record('USAGE_TOTAL', **fields))


def request_with_usage(call, *, scope, provider, model, emit, currency=None, visible=True, **context):
    """Instrument one transport call, including SDK calls hidden inside retries."""
    usage = None
    outcome = 'error'
    try:
        response = call()
        usage = normalize_usage(response, currency=currency)
        outcome = 'ok'
        return response
    finally:
        report_usage(usage, scope=scope, provider=provider, model=model, stage='transcription',
                     emit=emit, visible=visible, outcome=outcome, **context)
