class SttError(Exception):
    """Base error with a stable process exit code."""

    exit_code = 3


class ConfigError(SttError):
    exit_code = 2


class InputError(SttError):
    exit_code = 2


class ProviderError(SttError):
    exit_code = 20


class RetryExhaustedError(ProviderError):
    exit_code = 21
