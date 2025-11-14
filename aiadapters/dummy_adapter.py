from __future__ import annotations

from typing import List, Optional

from .base import LLMAdapter, Message


class DummyAdapter(LLMAdapter):
    """A minimal stub adapter for demos/tests.

    Echoes back the last user message content. Useful as a template for new
    providers.
    """

    def name(self) -> str:
        return "dummy"

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
        # Find the last non-system message and echo its content
        last = ""
        for m in messages:
            if m.get("role") != "system":
                last = m.get("content", last)
        return f"[DUMMY:{model or self.model or 'n/a'}] {last}"


