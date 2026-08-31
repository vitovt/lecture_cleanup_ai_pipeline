from __future__ import annotations

import http.client as http_client
import os
import unittest
from unittest.mock import patch

from aiadapters.base import LLMConnectionError
from aiadapters.openai_compatible_adapter import OpenAICompatibleChatAdapter


class IncompleteResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        raise http_client.IncompleteRead(b"x", 9)


class OpenAICompatibleTransportTests(unittest.TestCase):
    def test_incomplete_read_is_reported_as_retriable_connection_error(self) -> None:
        with patch.dict(os.environ, {"TEST_API_KEY": "secret"}):
            adapter = OpenAICompatibleChatAdapter(
                provider_name="test",
                api_key_env_var="TEST_API_KEY",
                default_api_base_url="https://example.invalid/v1",
                default_model="test-model",
            )

        with patch(
            "aiadapters.openai_compatible_adapter.urllib_request.urlopen",
            return_value=IncompleteResponse(),
        ):
            with self.assertRaises(LLMConnectionError):
                adapter.generate([{"role": "user", "content": "test"}])


if __name__ == "__main__":
    unittest.main()
