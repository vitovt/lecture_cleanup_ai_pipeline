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


class KieAdapter(LLMAdapter):
    """Kie AI adapter using its OpenAI-compatible chat completions endpoint.

    Expects KIE_API_KEY in the environment.
    Docs show per-model endpoints in the form:
      https://api.kie.ai/<model>/v1/chat/completions
    """

    def __init__(self, *, model: Optional[str] = None, temperature: Optional[float] = None, top_p: Optional[float] = None) -> None:
        super().__init__(model=model, temperature=temperature, top_p=top_p)
        self._api_key = os.environ.get("KIE_API_KEY")
        if not self._api_key:
            raise LLMAuthError("Missing KIE_API_KEY in environment (expected via .env or shell env)")
        api_base = (os.environ.get("KIE_API_BASE_URL") or "https://api.kie.ai").strip().rstrip("/")
        self._api_base = api_base or "https://api.kie.ai"
        self._OpenAI = None
        # Optional optimization: Kie chat completions are OpenAI-compatible.
        # We can reuse the OpenAI SDK client with a model-specific base_url when installed.
        try:
            from openai import OpenAI  # type: ignore
            self._OpenAI = OpenAI
        except Exception:
            self._OpenAI = None

    def name(self) -> str:
        return "kie"

    def validate_environment(self) -> None:
        if not os.environ.get("KIE_API_KEY"):
            raise LLMAuthError("Missing KIE_API_KEY in environment (expected via .env or shell env)")

    def _resolve_model(self, model: Optional[str]) -> str:
        model_name = (model or self.model or "gemini-2.5-pro").strip()
        if not model_name:
            raise LLMUnknownError("Kie model name is empty")
        return model_name

    def _endpoint_for_model(self, model_name: str) -> str:
        return f"{self._api_base}/{model_name}/v1/chat/completions"

    def _base_url_for_model(self, model_name: str) -> str:
        return f"{self._api_base}/{model_name}/v1"

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
        model_name = self._resolve_model(model)
        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": self._build_messages(messages),
            "stream": False,
        }
        temp_value = self.temperature if temperature is None else temperature
        top_p_value = self.top_p if top_p is None else top_p
        if temp_value is not None:
            payload["temperature"] = temp_value
        if top_p_value is not None:
            payload["top_p"] = top_p_value
        return payload

    @staticmethod
    def _json_loads_bytes(data: bytes) -> Optional[Dict[str, Any]]:
        try:
            decoded = data.decode("utf-8", errors="replace")
            parsed = json.loads(decoded)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    @staticmethod
    def _extract_error_message(parsed: Optional[Dict[str, Any]]) -> Optional[str]:
        if not parsed:
            return None
        code = parsed.get("code")
        msg = parsed.get("msg")
        if isinstance(code, int) and isinstance(msg, str) and msg.strip() and code != 200:
            return msg.strip()
        err = parsed.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("msg")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
        msg = parsed.get("message") or parsed.get("msg")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
        return None

    @staticmethod
    def _extract_text(parsed: Dict[str, Any]) -> str:
        # Some providers wrap the OpenAI-compatible response inside {"code","msg","data":{...}}
        wrapped = parsed.get("data")
        if isinstance(wrapped, dict):
            inner_text = KieAdapter._extract_text(wrapped)
            if inner_text:
                return inner_text
        if isinstance(wrapped, str) and wrapped.strip():
            try:
                nested = json.loads(wrapped)
            except Exception:
                return wrapped.strip()
            if isinstance(nested, dict):
                inner_text = KieAdapter._extract_text(nested)
                if inner_text:
                    return inner_text
        choices = parsed.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, dict):
                        content_text = KieAdapter._extract_text_from_unknown_message_content(content)
                        if content_text:
                            return content_text
                    reasoning_content = message.get("reasoning_content")
                    if isinstance(reasoning_content, str) and reasoning_content.strip():
                        return reasoning_content
                    refusal = message.get("refusal")
                    if isinstance(refusal, str) and refusal.strip():
                        return refusal
                    parts_field = message.get("parts")
                    if isinstance(parts_field, list):
                        parts_text = KieAdapter._extract_text_from_unknown_message_content(parts_field)
                        if parts_text:
                            return parts_text
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
                            nested_content = item.get("content")
                            if isinstance(nested_content, str):
                                parts.append(nested_content)
                        text = "".join(parts).strip()
                        if text:
                            return text
                    if isinstance(reasoning_content, list):
                        reason_text = KieAdapter._extract_text_from_unknown_message_content(reasoning_content)
                        if reason_text:
                            return reason_text
                # Some compatibility layers return text directly on choice.
                choice_text = first.get("text")
                if isinstance(choice_text, str) and choice_text.strip():
                    return choice_text
                delta = first.get("delta")
                if isinstance(delta, dict):
                    delta_text = KieAdapter._extract_text_from_unknown_message_content(delta.get("content"))
                    if delta_text:
                        return delta_text
        output_text = parsed.get("output_text")
        if isinstance(output_text, str):
            return output_text
        for key in ("text", "response", "result"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, dict):
                nested_text = KieAdapter._extract_text(value)
                if nested_text:
                    return nested_text
        candidates = parsed.get("candidates")
        if isinstance(candidates, list) and candidates:
            first_candidate = candidates[0]
            if isinstance(first_candidate, dict):
                content = first_candidate.get("content")
                if isinstance(content, dict):
                    parts = content.get("parts")
                    if isinstance(parts, list):
                        parts_text = KieAdapter._extract_text_from_unknown_message_content(parts)
                        if parts_text:
                            return parts_text
        return ""

    @staticmethod
    def _extract_text_from_unknown_message_content(content: Any) -> str:
        """Best-effort extraction for SDK objects with non-standard content shapes."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    # Common variants: {"type":"text","text":"..."} or nested {"content":"..."}
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                        continue
                    nested = item.get("content")
                    if isinstance(nested, str):
                        parts.append(nested)
                        continue
                    if isinstance(nested, list):
                        nested_text = KieAdapter._extract_text_from_unknown_message_content(nested)
                        if nested_text:
                            parts.append(nested_text)
                        continue
                # Pydantic/SDK typed objects may expose .text / .content attrs
                text_attr = getattr(item, "text", None)
                if isinstance(text_attr, str):
                    parts.append(text_attr)
                    continue
                content_attr = getattr(item, "content", None)
                if isinstance(content_attr, (str, list)):
                    content_text = KieAdapter._extract_text_from_unknown_message_content(content_attr)
                    if content_text:
                        parts.append(content_text)
            return "".join(parts).strip()
        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str):
                return text
            nested = content.get("content")
            if isinstance(nested, (str, list, dict)):
                return KieAdapter._extract_text_from_unknown_message_content(nested)
            return ""
        # SDK objects may still expose attrs even if not a dict/list.
        text_attr = getattr(content, "text", None)
        if isinstance(text_attr, str):
            return text_attr
        content_attr = getattr(content, "content", None)
        if isinstance(content_attr, (str, list, dict)):
            return KieAdapter._extract_text_from_unknown_message_content(content_attr)
        return ""

    def _raise_mapped_error(self, message: str, *, status: Optional[int], debug: bool) -> None:
        err_str = (message or "").lower()
        # Prefer explicit status classification first (Kie may use non-standard 433 for quota/points).
        if status in (401, 402, 403, 433):
            if debug:
                print(f"[DEBUG] {self.name()} mapped status={status} -> LLMAuthError")
            raise LLMAuthError(message)
        if status == 429:
            if debug:
                print(f"[DEBUG] {self.name()} mapped status={status} -> LLMRateLimitError")
            raise LLMRateLimitError(message)
        if any(k in err_str for k in ("rate limit", "too many requests", "retry_after", "retry in")):
            if debug:
                print(f"[DEBUG] {self.name()} mapped text match -> LLMRateLimitError")
            raise LLMRateLimitError(message)
        if any(k in err_str for k in (
            "unauthorized", "invalid api key", "forbidden", "permission", "401", "402", "403",
            "billing", "payment", "subscription", "credit",
            "usage points", "exceeded the total limit", "quota exceeded", "insufficient quota",
        )):
            # Kie sometimes returns generic 403/empty "Forbidden" style errors.
            # Add common Kie-specific causes to make troubleshooting actionable.
            generic_403 = status == 403 and (not message or message.strip().lower() in {
                "forbidden",
                "kie http error 403: forbidden",
                "no message available",
                "kie http error 403: no message available",
            })
            if generic_403:
                message = (
                    "Kie HTTP 403 Forbidden. Common causes: invalid/disabled KIE_API_KEY, "
                    "IP whitelist restriction on the key, no access to this model, or account/credit restrictions. "
                    "Check Kie dashboard logs and test GET https://api.kie.ai/api/v1/chat/credit with the same key."
                )
            if debug:
                print(f"[DEBUG] {self.name()} mapped status={status} -> LLMAuthError")
            raise LLMAuthError(message)
        if status is not None and (status >= 500 or status == 408):
            if debug:
                print(f"[DEBUG] {self.name()} mapped status={status} -> LLMConnectionError")
            raise LLMConnectionError(message)
        if any(k in err_str for k in ("timeout", "temporarily unavailable", "connection", "dns", "unavailable", "maintenance", "maintained", "try again later")):
            if debug:
                print(f"[DEBUG] {self.name()} mapped text match -> LLMConnectionError")
            raise LLMConnectionError(message)
        if debug:
            print(f"[DEBUG] {self.name()} mapped status={status} -> LLMUnknownError")
        raise LLMUnknownError(message)

    def _raise_if_kie_envelope_error(self, parsed: Dict[str, Any], *, debug: bool) -> None:
        """Kie may return HTTP 200 with an app-level error envelope like {"code":500,"msg":"..."}."""
        code = parsed.get("code")
        if not isinstance(code, int):
            return
        if code == 200:
            return
        msg = self._extract_error_message(parsed) or f"Kie API error code={code}"
        # Preserve semantics: app-level 5xx are transient; app-level 4xx/433 are auth/billing/quota-like.
        status = code if code >= 400 else None
        self._raise_mapped_error(msg, status=status, debug=debug)

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
        """Human-friendly hints for common proxy/CDN non-standard statuses."""
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

        reason = ""
        try:
            raw_reason = getattr(http_error, "reason", None)
            if raw_reason is not None:
                reason = str(raw_reason).strip()
        except Exception:
            reason = ""

        hint = self._status_hint(status)
        if status is not None:
            if reason:
                base = f"Kie HTTP error {status}: {reason}"
            elif hint:
                base = f"Kie HTTP error {status}: {hint}"
            else:
                base = f"Kie HTTP error {status}"
        else:
            base = f"Kie HTTP error: {http_error}"

        preview = self._short_body_preview(err_body)
        if preview:
            return f"{base} | body: {preview}"
        return base

    def _build_sdk_params(
        self,
        messages: List[Message],
        *,
        model: Optional[str],
        temperature: Optional[float],
        top_p: Optional[float],
    ) -> Dict[str, Any]:
        model_name = self._resolve_model(model)
        params: Dict[str, Any] = {
            "model": model_name,
            "messages": self._build_messages(messages),
            "stream": False,
        }
        temp_value = self.temperature if temperature is None else temperature
        top_p_value = self.top_p if top_p is None else top_p
        if temp_value is not None:
            params["temperature"] = temp_value
        if top_p_value is not None:
            params["top_p"] = top_p_value
        return params

    def _generate_via_openai_sdk(
        self,
        messages: List[Message],
        *,
        model: Optional[str],
        temperature: Optional[float],
        top_p: Optional[float],
        debug: bool,
        label: Optional[str],
    ) -> str:
        if self._OpenAI is None:
            raise LLMUnknownError("OpenAI SDK not available for Kie OpenAI-compatible mode")

        params = self._build_sdk_params(messages, model=model, temperature=temperature, top_p=top_p)
        model_name = str(params["model"])
        base_url = self._base_url_for_model(model_name)

        if debug:
            print("===== DEBUG: Kie request BEGIN" + (f" [{label}]" if label else "") + " =====")
            print(f"Base URL (OpenAI SDK): {base_url}")
            print(f"Model: {model_name} | temperature: {params.get('temperature')} | top_p: {params.get('top_p')}")
            print(f"Messages: {len(params.get('messages', []))} (system={sum(1 for m in params.get('messages', []) if m.get('role') == 'system')})")
            print("===== DEBUG: Kie request END =====")

        client = self._OpenAI(api_key=self._api_key, base_url=base_url)
        try:
            resp = client.chat.completions.create(**params)
            dumped: Optional[Dict[str, Any]] = None
            if hasattr(resp, "model_dump"):
                try:
                    maybe_dumped = resp.model_dump()  # type: ignore[attr-defined]
                    if isinstance(maybe_dumped, dict):
                        dumped = maybe_dumped
                except Exception:
                    dumped = None
            if dumped is not None:
                self._raise_if_kie_envelope_error(dumped, debug=debug)
            choices = getattr(resp, "choices", None) or []
            if choices:
                first = choices[0]
                msg = getattr(first, "message", None)
                if msg is not None:
                    content = getattr(msg, "content", None)
                    text = self._extract_text_from_unknown_message_content(content)
                    if text:
                        return text
                    # Some providers expose reasoning separately; prefer final answer but
                    # use reasoning text as a last-resort non-empty payload to avoid false empties.
                    reasoning_content = getattr(msg, "reasoning_content", None)
                    text = self._extract_text_from_unknown_message_content(reasoning_content)
                    if text:
                        if debug:
                            print(f"[DEBUG] {self.name()} SDK response used message.reasoning_content fallback")
                        return text
            # Also support raw dict-like serialization if the SDK object stores extra fields.
            if dumped is not None:
                text = self._extract_text(dumped)
                if text:
                    return text
                if debug:
                    preview = self._short_body_preview(json.dumps(dumped, ensure_ascii=False).encode("utf-8"))
                    if preview:
                        print(f"[DEBUG] {self.name()} SDK response dump (empty text): {preview}")
            return ""
        except Exception as e:
            self._raise_mapped_error(str(e), status=None, debug=debug)
            raise  # pragma: no cover

    def _generate_via_urllib(
        self,
        messages: List[Message],
        *,
        model: Optional[str],
        temperature: Optional[float],
        top_p: Optional[float],
        debug: bool,
        label: Optional[str],
    ) -> str:
        payload = self._build_payload(messages, model=model, temperature=temperature, top_p=top_p)
        model_name = str(payload["model"])
        endpoint = self._endpoint_for_model(model_name)

        if debug:
            print("===== DEBUG: Kie request BEGIN" + (f" [{label}]" if label else "") + " =====")
            print(f"Endpoint: {endpoint}")
            print(f"Model: {model_name} | temperature: {payload.get('temperature')} | top_p: {payload.get('top_p')}")
            print(f"Messages: {len(payload.get('messages', []))} (system={sum(1 for m in payload.get('messages', []) if m.get('role') == 'system')})")
            print("===== DEBUG: Kie request END =====")

        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "User-Agent": "lecture-cleanup-pipeline/1.0 (+KieAdapter urllib)",
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
                    raise LLMUnknownError("Kie response is not valid JSON")
                self._raise_if_kie_envelope_error(parsed, debug=debug)
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
            provider_msg = self._extract_error_message(parsed)
            message = self._format_http_error_message(
                status=status,
                http_error=e,
                provider_msg=provider_msg,
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
        # Prefer raw HTTP first: simpler behavior, exact response visibility, and avoids
        # double-billing when the SDK path returns an empty but otherwise successful response.
        try:
            raw_text = self._generate_via_urllib(
                messages,
                model=model,
                temperature=temperature,
                top_p=top_p,
                debug=debug,
                label=label,
            )
            if raw_text:
                return raw_text
            return ""
        except LLMAuthError:
            raise
        except (LLMConnectionError, LLMRateLimitError):
            raise
        except LLMUnknownError as e:
            if debug:
                print(f"[DEBUG] {self.name()} urllib path failed, trying OpenAI SDK fallback: {e}")
            if self._OpenAI is None:
                raise
            return self._generate_via_openai_sdk(
                messages,
                model=model,
                temperature=temperature,
                top_p=top_p,
                debug=debug,
                label=label,
            )
