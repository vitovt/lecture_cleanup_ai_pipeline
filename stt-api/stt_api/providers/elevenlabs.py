from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Callable

from ..errors import ProviderError, ProviderRequestError, RetryExhaustedError


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _response_words(response: Any, *, timestamps: bool) -> list[dict[str, Any]]:
    if not timestamps:
        return []
    result: list[dict[str, Any]] = []
    for word in _value(response, "words", []) or []:
        if _value(word, "type") != "word":
            continue
        text = str(_value(word, "text", "") or "").strip()
        start = _value(word, "start")
        end = _value(word, "end")
        if not text or start is None or end is None:
            continue
        result.append(
            {
                "text": text,
                "start": float(start),
                "end": float(end),
                "speaker": _value(word, "speaker_id"),
            }
        )
    return result


class ElevenLabsProvider:
    def __init__(
        self,
        api_key: str,
        *,
        attempts: int,
        initial_delay: float,
        multiplier: float,
        max_delay: float,
        jitter: float,
        request_timeout: float,
        tag_audio_events: bool,
        client_factory: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if client_factory is None:
            try:
                from elevenlabs.client import ElevenLabs
            except ImportError as exc:
                raise ProviderError(
                    "elevenlabs is not installed; run stt-api/setup_venv.sh"
                ) from exc
            client_factory = ElevenLabs
        self.client = client_factory(api_key=api_key, timeout=request_timeout)
        self.attempts = attempts
        self.initial_delay = initial_delay
        self.multiplier = multiplier
        self.max_delay = max_delay
        self.jitter = jitter
        self.tag_audio_events = tag_audio_events
        self.sleeper = sleeper

    def transcribe(
        self,
        path: Path,
        *,
        model: str,
        language_codes: list[str],
        vocabulary: list[str],
        mode: str,
        timestamps: bool,
        diarization: bool,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model_id": model,
            "timestamps_granularity": "word" if timestamps else "none",
            "diarize": diarization,
            "tag_audio_events": self.tag_audio_events,
            "no_verbatim": mode == "smart",
        }
        # Batch Scribe accepts one language hint. Multiple requested workflow
        # languages intentionally enable its automatic multilingual detection.
        if len(language_codes) == 1:
            request["language_code"] = language_codes[0].split("-", 1)[0].lower()
        if vocabulary:
            request["keyterms"] = vocabulary

        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                with path.open("rb") as audio_file:
                    response = self.client.speech_to_text.convert(
                        file=audio_file,
                        **request,
                    )
                return {
                    "text": str(_value(response, "text", "") or "").strip(),
                    "words": _response_words(response, timestamps=timestamps),
                    "language_code": str(
                        _value(response, "language_code", "") or ""
                    ),
                    "language_probability": _value(
                        response, "language_probability"
                    ),
                }
            except Exception as exc:  # SDK transport/error classes evolve.
                last_error = exc
                status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                try:
                    status = int(status) if status is not None else None
                except (TypeError, ValueError):
                    status = None
                retryable = status in {408, 409, 429, 500, 502, 503, 504} or status is None
                if not retryable:
                    message = str(exc)
                    account_wide = status in {401, 403, 404} or any(
                        marker in message.casefold()
                        for marker in (
                            "api key",
                            "billing",
                            "quota",
                            "permission",
                            "model not found",
                            "model is not found",
                            "subscription",
                        )
                    )
                    error_type = ProviderError if account_wide else ProviderRequestError
                    raise error_type(f"ElevenLabs request failed: {message}") from exc
                if attempt + 1 >= self.attempts:
                    break
                delay = min(self.max_delay, self.initial_delay * self.multiplier**attempt)
                delay += random.uniform(0, max(0.0, self.jitter))
                self.sleeper(delay)
        raise RetryExhaustedError(
            f"ElevenLabs request failed after {self.attempts} attempts: {last_error}"
        ) from last_error
