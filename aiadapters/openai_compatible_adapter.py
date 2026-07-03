from __future__ import annotations

import json
import os
import socket
from typing import Any, Dict, List, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

from .base import (
    LLMAdapter,
    LLMAuthError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMUnknownError,
    Message,
)


class OpenAICompatibleChatAdapter(LLMAdapter):
    """Reusable adapter for OpenAI-compatible non-stream chat completions APIs."""

    def __init__(
        self,
        *,
        provider_name: str,
        api_key_env_var: str,
        default_model: str,
        default_api_base_url: str,
        api_base_url_env_var: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        reasoning_effort: Optional[str] = None,
        reasoning_format: Optional[str] = None,
        thinking: Optional[str] = None,
        api_base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        user_agent_suffix: Optional[str] = None,
    ) -> None:
        super().__init__(model=model, temperature=temperature, top_p=top_p)
        self._provider_name = provider_name.strip().lower()
        self._provider_label = provider_name.strip() or "OpenAI-compatible"
        self._api_key_env_var = api_key_env_var
        self._default_model = default_model
        self._api_key = os.environ.get(api_key_env_var)
        if not self._api_key:
            raise LLMAuthError(
                f"Missing {api_key_env_var} in environment (expected via .env or shell env)"
            )
        env_base_url = os.environ.get(api_base_url_env_var or "") if api_base_url_env_var else None
        self._api_base = (
            (api_base_url or env_base_url or default_api_base_url)
            .strip()
            .rstrip("/")
        ) or default_api_base_url.rstrip("/")
        self._reasoning_effort = (reasoning_effort or "").strip() or None
        self._reasoning_format = (reasoning_format or "").strip() or None
        self._thinking = (thinking or "").strip().lower() or None
        self._timeout_seconds = float(timeout_seconds) if timeout_seconds is not None else 300.0
        suffix = (user_agent_suffix or self.__class__.__name__).strip()
        self._user_agent = f"lecture-cleanup-pipeline/1.0 (+{suffix})"

    def name(self) -> str:
        return self._provider_name

    def validate_environment(self) -> None:
        if not os.environ.get(self._api_key_env_var):
            raise LLMAuthError(
                f"Missing {self._api_key_env_var} in environment (expected via .env or shell env)"
            )

    def _resolve_model(self, model: Optional[str]) -> str:
        model_name = (model or self.model or self._default_model).strip()
        if not model_name:
            raise LLMUnknownError(f"{self._provider_label} model name is empty")
        return model_name

    def _endpoint(self) -> str:
        return f"{self._api_base}/chat/completions"

    def _build_messages(self, messages: List[Message]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for msg in messages:
            role = str(msg.get("role", "user") or "user").strip().lower()
            if role not in ("system", "user", "assistant"):
                role = "user"
            out.append(
                {
                    "role": role,
                    "content": str(msg.get("content", "") or ""),
                }
            )
        return out

    def _build_payload(
        self,
        messages: List[Message],
        *,
        model: Optional[str],
        temperature: Optional[float],
        top_p: Optional[float],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self._resolve_model(model),
            "messages": self._build_messages(messages),
            "stream": False,
        }
        temp_value = self.temperature if temperature is None else temperature
        top_p_value = self.top_p if top_p is None else top_p
        if temp_value is not None:
            payload["temperature"] = temp_value
        if top_p_value is not None:
            payload["top_p"] = top_p_value
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        if self._reasoning_format:
            payload["reasoning_format"] = self._reasoning_format
        if self._thinking:
            payload["thinking"] = {"type": self._thinking}
        return payload

    @staticmethod
    def _json_loads_bytes(data: bytes) -> Optional[Dict[str, Any]]:
        try:
            parsed = json.loads(data.decode("utf-8", errors="replace"))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    @staticmethod
    def _short_body_preview(data: bytes) -> str:
        if not data:
            return ""
        text = data.decode("utf-8", errors="replace").strip()
        if len(text) > 800:
            return text[:800] + "…"
        return text

    @staticmethod
    def _extract_error_message(parsed: Optional[Dict[str, Any]]) -> Optional[str]:
        if not parsed:
            return None
        err = parsed.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("msg")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
            code = err.get("code")
            if isinstance(code, str) and code.strip():
                return code.strip()
        for key in ("message", "msg", "detail"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @classmethod
    def _extract_text_from_unknown_content(cls, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
                nested = item.get("content")
                if isinstance(nested, (str, list, dict)):
                    nested_text = cls._extract_text_from_unknown_content(nested)
                    if nested_text:
                        parts.append(nested_text)
            return "".join(parts).strip()
        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str):
                return text.strip()
            nested = content.get("content")
            if isinstance(nested, (str, list, dict)):
                return cls._extract_text_from_unknown_content(nested)
        return ""

    @classmethod
    def _extract_text(cls, parsed: Dict[str, Any]) -> str:
        choices = parsed.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    text = cls._extract_text_from_unknown_content(message.get("content"))
                    if text:
                        return text
                text = cls._extract_text_from_unknown_content(first.get("text"))
                if text:
                    return text
        for key in ("output_text", "text", "response", "result"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = cls._extract_text(value)
                if nested:
                    return nested
        return ""

    @staticmethod
    def _status_hint(status: Optional[int]) -> str:
        hints = {
            520: "Cloudflare unknown origin error",
            522: "Cloudflare connection timeout (origin did not connect in time)",
            523: "Cloudflare origin unreachable",
            524: "Cloudflare timeout (origin took too long to respond)",
            525: "Cloudflare SSL handshake failed",
            526: "Cloudflare invalid SSL certificate",
            530: "Cloudflare origin error",
        }
        if status is None:
            return ""
        return hints.get(int(status), "")

    def _format_http_error_message(
        self,
        *,
        status: Optional[int],
        http_error: Exception,
        provider_msg: Optional[str],
        err_body: bytes,
    ) -> str:
        if provider_msg:
            base = provider_msg
        else:
            raw_reason = getattr(http_error, "reason", None)
            reason = str(raw_reason).strip() if raw_reason is not None else ""
            hint = self._status_hint(status)
            if status is not None:
                if reason:
                    base = f"{self._provider_label} HTTP error {status}: {reason}"
                elif hint:
                    base = f"{self._provider_label} HTTP error {status}: {hint}"
                else:
                    base = f"{self._provider_label} HTTP error {status}"
            else:
                base = f"{self._provider_label} HTTP error: {http_error}"

        retry_after = ""
        try:
            retry_after_raw = getattr(http_error, "headers", {}).get("retry-after")
            if retry_after_raw:
                retry_after = f" retry in {retry_after_raw}s"
        except Exception:
            retry_after = ""

        preview = self._short_body_preview(err_body)
        if preview and not provider_msg:
            return f"{base}{retry_after} | body: {preview}"
        return f"{base}{retry_after}"

    def _raise_mapped_error(self, message: str, *, status: Optional[int], debug: bool) -> None:
        err_str = (message or "").lower()
        if status in (401, 402, 403):
            if debug:
                print(f"[DEBUG] {self.name()} mapped status={status} -> LLMAuthError")
            raise LLMAuthError(message)
        if status == 429:
            if debug:
                print(f"[DEBUG] {self.name()} mapped status={status} -> LLMRateLimitError")
            raise LLMRateLimitError(message)
        if any(k in err_str for k in ("rate limit", "too many requests", "retry after", "retry in")):
            if debug:
                print(f"[DEBUG] {self.name()} mapped text match -> LLMRateLimitError")
            raise LLMRateLimitError(message)
        if any(
            k in err_str
            for k in (
                "unauthorized",
                "invalid api key",
                "invalid token",
                "forbidden",
                "permission",
                "401",
                "402",
                "403",
                "billing",
                "payment",
                "subscription",
                "credit",
                "balance",
                "insufficient balance",
                "spend limit",
                "model is blocked",
            )
        ):
            if debug:
                print(f"[DEBUG] {self.name()} mapped text match -> LLMAuthError")
            raise LLMAuthError(message)
        if status is not None and (status >= 500 or status in (408, 409, 498)):
            if debug:
                print(f"[DEBUG] {self.name()} mapped status={status} -> LLMConnectionError")
            raise LLMConnectionError(message)
        if any(
            k in err_str
            for k in ("timeout", "temporarily unavailable", "unavailable", "connection", "dns", "maintenance")
        ):
            if debug:
                print(f"[DEBUG] {self.name()} mapped text match -> LLMConnectionError")
            raise LLMConnectionError(message)
        if debug:
            print(f"[DEBUG] {self.name()} mapped status={status} -> LLMUnknownError")
        raise LLMUnknownError(message)

    def generate(
        self,
        messages: List[Message],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        debug: bool = False,
        label: Optional[str] = None,
    ) -> str:
        payload = self._build_payload(messages, model=model, temperature=temperature, top_p=top_p)
        endpoint = self._endpoint()

        if debug:
            print(
                f"===== DEBUG: {self._provider_label} request BEGIN"
                + (f" [{label}]" if label else "")
                + " ====="
            )
            print(f"Endpoint: {endpoint}")
            print(
                f"Model: {payload.get('model')} | temperature: {payload.get('temperature')} "
                f"| top_p: {payload.get('top_p')} | reasoning_effort: {payload.get('reasoning_effort')} "
                f"| reasoning_format: {payload.get('reasoning_format')} | thinking: {payload.get('thinking')}"
            )
            print(
                f"Messages: {len(payload.get('messages', []))} "
                f"(system={sum(1 for m in payload.get('messages', []) if m.get('role') == 'system')})"
            )
            print(f"===== DEBUG: {self._provider_label} request END =====")

        req = urllib_request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "User-Agent": self._user_agent,
            },
        )

        try:
            with urllib_request.urlopen(req, timeout=self._timeout_seconds) as resp:
                raw = resp.read()
                parsed = self._json_loads_bytes(raw)
                if not parsed:
                    if debug:
                        preview = self._short_body_preview(raw)
                        if preview:
                            print(f"[DEBUG] {self.name()} non-JSON success body: {preview}")
                    raise LLMUnknownError(f"{self._provider_label} response is not valid JSON")
                text = self._extract_text(parsed)
                if text:
                    return text
                if debug:
                    preview = self._short_body_preview(raw)
                    if preview:
                        print(f"[DEBUG] {self.name()} success JSON body (empty text after parse): {preview}")
                return ""
        except urllib_error.HTTPError as e:
            status = getattr(e, "code", None)
            err_body = b""
            try:
                err_body = e.read()
            except Exception:
                err_body = b""
            if debug:
                preview = self._short_body_preview(err_body)
                if preview:
                    print(f"[DEBUG] {self.name()} HTTP {status} body: {preview}")
            parsed = self._json_loads_bytes(err_body)
            message = self._format_http_error_message(
                status=status,
                http_error=e,
                provider_msg=self._extract_error_message(parsed),
                err_body=err_body,
            )
            self._raise_mapped_error(message, status=status, debug=debug)
            raise  # pragma: no cover
        except urllib_error.URLError as e:
            raise LLMConnectionError(str(e)) from e
        except (TimeoutError, socket.timeout) as e:
            raise LLMConnectionError(str(e)) from e
        except (LLMAuthError, LLMConnectionError, LLMRateLimitError, LLMUnknownError):
            raise
        except Exception as e:
            self._raise_mapped_error(str(e), status=None, debug=debug)
            raise  # pragma: no cover
