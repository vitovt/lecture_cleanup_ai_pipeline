from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Callable

from ..errors import ProviderError, ProviderRequestError, RetryExhaustedError
from ..formatter import normalize_words


class GeminiProvider:
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
        client_factory: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if client_factory is None:
            try:
                from google import genai
            except ImportError as exc:
                raise ProviderError(
                    "google-genai is not installed; run stt-api/setup_venv.sh"
                ) from exc
            client_factory = genai.Client
        self.client = client_factory(api_key=api_key)
        self.attempts = attempts
        self.initial_delay = initial_delay
        self.multiplier = multiplier
        self.max_delay = max_delay
        self.jitter = jitter
        self.request_timeout = request_timeout
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
        transcription_config: dict[str, Any] = {"language_codes": language_codes}
        if vocabulary:
            transcription_config["custom_vocabulary"] = vocabulary
        if mode == "smart":
            transcription_config["mode"] = "smart"
        else:
            mode_config: dict[str, Any] = {"type": "verbatim"}
            if timestamps:
                mode_config["timestamp_granularities"] = ["word"]
            if diarization:
                mode_config["diarization_mode"] = "speaker"
            transcription_config["mode"] = mode_config

        last_error: Exception | None = None
        for attempt in range(self.attempts):
            uploaded = None
            try:
                uploaded = self.client.files.upload(file=str(path))
                interaction = self.client.interactions.create(
                    model=model,
                    input=[
                        {
                            "type": "audio",
                            "uri": uploaded.uri,
                            "mime_type": uploaded.mime_type,
                        }
                    ],
                    generation_config={"transcription_config": transcription_config},
                    timeout=self.request_timeout,
                )
                return {
                    "text": str(getattr(interaction, "output_text", "") or "").strip(),
                    "words": normalize_words(interaction),
                    "interaction_id": getattr(interaction, "id", None),
                }
            except Exception as exc:  # SDK exposes several evolving transport classes.
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
                            "api key", "billing", "quota", "permission",
                            "model not found", "model is not found",
                        )
                    )
                    error_type = ProviderError if account_wide else ProviderRequestError
                    raise error_type(f"Gemini request failed: {message}") from exc
                if attempt + 1 >= self.attempts:
                    break
                delay = min(self.max_delay, self.initial_delay * self.multiplier**attempt)
                delay += random.uniform(0, max(0.0, self.jitter))
                self.sleeper(delay)
            finally:
                if uploaded is not None:
                    name = getattr(uploaded, "name", None)
                    if name:
                        try:
                            self.client.files.delete(name=name)
                        except Exception:
                            pass
        raise RetryExhaustedError(
            f"Gemini request failed after {self.attempts} attempts: {last_error}"
        ) from last_error
