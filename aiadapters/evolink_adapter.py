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


class EvoLinkAdapter(LLMAdapter):
    """EvoLink Gemini Native API adapter.

    Uses the EvoLink native endpoint shape documented for Gemini language models:
      POST https://api.evolink.ai/v1beta/models/{model}:{method}
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        method: Optional[str] = None,
        api_base_url: Optional[str] = None,
    ) -> None:
        super().__init__(model=model, temperature=temperature, top_p=top_p)
        self._api_key = os.environ.get("EVOLINK_API_KEY")
        if not self._api_key:
            raise LLMAuthError("Missing EVOLINK_API_KEY in environment (expected via .env or shell env)")
        self._api_base = (
            (api_base_url or os.environ.get("EVOLINK_API_BASE_URL") or "https://api.evolink.ai")
            .strip()
            .rstrip("/")
        ) or "https://api.evolink.ai"
        self._method = (method or "generateContent").strip() or "generateContent"

    def name(self) -> str:
        return "evolink"

    def validate_environment(self) -> None:
        if not os.environ.get("EVOLINK_API_KEY"):
            raise LLMAuthError("Missing EVOLINK_API_KEY in environment (expected via .env or shell env)")

    def _resolve_model(self, model: Optional[str]) -> str:
        model_name = (model or self.model or "gemini-2.5-pro").strip()
        if not model_name:
            raise LLMUnknownError("EvoLink model name is empty")
        return model_name

    def _endpoint(self, model_name: str) -> str:
        return f"{self._api_base}/v1beta/models/{model_name}:{self._method}"

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
            return provider_msg
        raw_reason = getattr(http_error, "reason", None)
        reason = str(raw_reason).strip() if raw_reason is not None else ""
        if reason.lower() == "<none>":
            reason = ""
        hint = self._status_hint(status)
        if status is not None:
            if reason:
                base = f"EvoLink HTTP error {status}: {reason}"
            elif hint:
                base = f"EvoLink HTTP error {status}: {hint}"
            else:
                base = f"EvoLink HTTP error {status}"
        else:
            base = f"EvoLink HTTP error: {http_error}"
        preview = self._short_body_preview(err_body)
        if preview:
            return f"{base} | body: {preview}"
        return base

    @staticmethod
    def _extract_error_message(parsed: Optional[Dict[str, Any]]) -> Optional[str]:
        if not parsed:
            return None
        code = parsed.get("code")
        msg = parsed.get("msg")
        if isinstance(code, int) and code != 200 and isinstance(msg, str) and msg.strip():
            return msg.strip()
        err = parsed.get("error")
        if isinstance(err, dict):
            err_msg = err.get("message") or err.get("msg")
            if isinstance(err_msg, str) and err_msg.strip():
                return err_msg.strip()
        for key in ("message", "msg", "detail"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _raise_mapped_error(self, message: str, *, status: Optional[int], debug: bool) -> None:
        err_str = (message or "").lower()
        # Prefer explicit HTTP/app status classification first to avoid false positives from request IDs
        # that may contain digit sequences like "429".
        if status in (401, 402, 403):
            if debug:
                print(f"[DEBUG] {self.name()} mapped status={status} -> LLMAuthError")
            raise LLMAuthError(message)
        if status == 429:
            if debug:
                print(f"[DEBUG] {self.name()} mapped status={status} -> LLMRateLimitError")
            raise LLMRateLimitError(message)
        if any(k in err_str for k in ("rate limit", "too many requests", "retry after", "quota exceeded")):
            if debug:
                print(f"[DEBUG] {self.name()} mapped text match -> LLMRateLimitError")
            raise LLMRateLimitError(message)
        if any(k in err_str for k in ("unauthorized", "invalid api key", "invalid token", "forbidden", "permission", "401", "402", "403", "billing", "payment", "subscription", "credit", "无效的令牌")):
            if debug:
                print(f"[DEBUG] {self.name()} mapped text match -> LLMAuthError")
            raise LLMAuthError(message)
        if status is not None and (status >= 500 or status == 408):
            if debug:
                print(f"[DEBUG] {self.name()} mapped status={status} -> LLMConnectionError")
            raise LLMConnectionError(message)
        if any(k in err_str for k in ("timeout", "temporarily unavailable", "unavailable", "connection", "dns", "maintenance", "try again later")):
            if debug:
                print(f"[DEBUG] {self.name()} mapped text match -> LLMConnectionError")
            raise LLMConnectionError(message)
        if debug:
            print(f"[DEBUG] {self.name()} mapped status={status} -> LLMUnknownError")
        raise LLMUnknownError(message)

    def _raise_if_app_error(self, parsed: Dict[str, Any], *, debug: bool) -> None:
        code = parsed.get("code")
        if not isinstance(code, int) or code == 200:
            return
        msg = self._extract_error_message(parsed) or f"EvoLink API error code={code}"
        self._raise_mapped_error(msg, status=(code if code >= 400 else None), debug=debug)

    @staticmethod
    def _extract_text_from_parts(parts: Any) -> str:
        if not isinstance(parts, list):
            return ""
        out: List[str] = []
        for part in parts:
            if isinstance(part, str):
                out.append(part)
                continue
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                out.append(text)
                continue
            nested = part.get("content")
            if isinstance(nested, str):
                out.append(nested)
        return "".join(out).strip()

    def _extract_text(self, parsed: Dict[str, Any]) -> str:
        candidates = parsed.get("candidates")
        if isinstance(candidates, list) and candidates:
            first = candidates[0]
            if isinstance(first, dict):
                content = first.get("content")
                if isinstance(content, dict):
                    text = self._extract_text_from_parts(content.get("parts"))
                    if text:
                        return text
                first_text = first.get("text")
                if isinstance(first_text, str) and first_text.strip():
                    return first_text.strip()

        wrapped = parsed.get("data")
        if isinstance(wrapped, dict):
            text = self._extract_text(wrapped)
            if text:
                return text
        if isinstance(wrapped, str) and wrapped.strip():
            try:
                nested = json.loads(wrapped)
            except Exception:
                return wrapped.strip()
            if isinstance(nested, dict):
                text = self._extract_text(nested)
                if text:
                    return text

        choices = parsed.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
                first_text = first.get("text")
                if isinstance(first_text, str) and first_text.strip():
                    return first_text.strip()

        for key in ("text", "response", "result", "output_text"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _build_contents(self, messages: List[Message]) -> List[Dict[str, Any]]:
        system_parts: List[str] = []
        contents: List[Dict[str, Any]] = []
        for m in messages:
            role = str(m.get("role", "user") or "user").strip().lower()
            text = str(m.get("content", "") or "")
            if not text:
                continue
            if role == "system":
                system_parts.append(text)
                continue
            native_role = "model" if role == "assistant" else "user"
            contents.append({"role": native_role, "parts": [{"text": text}]})

        if system_parts:
            sys_text = "\n\n".join(system_parts).strip()
            if sys_text:
                # Quickstart documents only `contents`; encode system prompt as a leading user turn.
                contents.insert(0, {"role": "user", "parts": [{"text": f"[SYSTEM INSTRUCTION]\n{sys_text}"}]})

        if not contents:
            contents = [{"role": "user", "parts": [{"text": ""}]}]
        return contents

    def _build_payload(
        self,
        messages: List[Message],
        *,
        model: Optional[str],
        temperature: Optional[float],
        top_p: Optional[float],
    ) -> Dict[str, Any]:
        _ = self._resolve_model(model)  # validate
        payload: Dict[str, Any] = {"contents": self._build_contents(messages)}
        gen_cfg: Dict[str, Any] = {}
        temp_value = self.temperature if temperature is None else temperature
        top_p_value = self.top_p if top_p is None else top_p
        if temp_value is not None:
            gen_cfg["temperature"] = temp_value
        if top_p_value is not None:
            gen_cfg["topP"] = top_p_value
        if gen_cfg:
            payload["generationConfig"] = gen_cfg
        return payload

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
        model_name = self._resolve_model(model)
        endpoint = self._endpoint(model_name)
        payload = self._build_payload(messages, model=model_name, temperature=temperature, top_p=top_p)

        if debug:
            print("===== DEBUG: EvoLink request BEGIN" + (f" [{label}]" if label else "") + " =====")
            print(f"Endpoint: {endpoint}")
            gen_cfg = payload.get("generationConfig", {})
            if not isinstance(gen_cfg, dict):
                gen_cfg = {}
            print(f"Model: {model_name} | method: {self._method} | temperature: {gen_cfg.get('temperature')} | topP: {gen_cfg.get('topP')}")
            print(f"Contents: {len(payload.get('contents', []))}")
            print("===== DEBUG: EvoLink request END =====")

        req = urllib_request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "User-Agent": "lecture-cleanup-pipeline/1.0 (+EvoLinkAdapter native)",
            },
        )

        try:
            with urllib_request.urlopen(req, timeout=300) as resp:
                raw = resp.read()
                parsed = self._json_loads_bytes(raw)
                if not parsed:
                    if debug:
                        preview = self._short_body_preview(raw)
                        if preview:
                            print(f"[DEBUG] {self.name()} non-JSON success body: {preview}")
                    raise LLMUnknownError("EvoLink response is not valid JSON")
                self._raise_if_app_error(parsed, debug=debug)
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
            msg = self._format_http_error_message(
                status=status,
                http_error=e,
                provider_msg=self._extract_error_message(parsed),
                err_body=err_body,
            )
            self._raise_mapped_error(msg, status=status, debug=debug)
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
