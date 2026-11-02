"""Small read-only JSON transport; errors never include credentials or bodies."""
import json
from decimal import Decimal
import math
from urllib import error as urllib_error, request as urllib_request


class AccountError(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def check_timeout(value):
    if isinstance(value, bool):
        raise AccountError('invalid_configuration')
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise AccountError('invalid_configuration') from None
    if not math.isfinite(value) or not 0 < value <= 60:
        raise AccountError('invalid_configuration')
    return value


def get_json(url, headers, timeout=10):
    timeout = check_timeout(timeout)
    request = urllib_request.Request(url, headers={
        'Accept': 'application/json', 'User-Agent': 'lecture-cleanup-pipeline/1.0', **headers})
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except urllib_error.HTTPError as exc:
        reason = {401: 'authentication_failed', 403: 'permission_denied',
                  429: 'rate_limited'}.get(exc.code, 'http_error')
        raise AccountError(reason) from None
    except Exception:
        raise AccountError('connection_failed') from None
    try:
        result = json.loads(data, parse_float=Decimal)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, UnicodeError):
        raise AccountError('invalid_response') from None
