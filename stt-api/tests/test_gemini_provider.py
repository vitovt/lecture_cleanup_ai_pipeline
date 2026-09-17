import unittest
from pathlib import Path
from types import SimpleNamespace

from stt_api.providers.gemini import GeminiProvider


class FakeFiles:
    def __init__(self):
        self.deleted = []

    def upload(self, *, file):
        return SimpleNamespace(uri="file://audio", mime_type="audio/flac", name="files/1")

    def delete(self, *, name):
        self.deleted.append(name)


class FakeInteractions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        annotation = SimpleNamespace(
            type="word_info", text="Hallo", start_offset="1.25s", end_offset="1.5s", speaker=None
        )
        content = SimpleNamespace(annotations=[annotation])
        return SimpleNamespace(output_text="Hallo", id="interactions/1", steps=[SimpleNamespace(content=[content])])


class FakeClient:
    def __init__(self, **_kwargs):
        self.files = FakeFiles()
        self.interactions = FakeInteractions()


class GeminiProviderTests(unittest.TestCase):
    def test_official_interactions_contract_and_cleanup(self):
        provider = GeminiProvider(
            "secret", attempts=1, initial_delay=0, multiplier=1, max_delay=0,
            jitter=0, request_timeout=180, client_factory=FakeClient,
        )
        result = provider.transcribe(
            Path("audio.flac"), model="gemini-3.5-transcribe",
            language_codes=["uk-UA", "de-DE"], vocabulary=[], mode="verbatim",
            timestamps=True, diarization=False,
        )
        config = provider.client.interactions.kwargs["generation_config"]["transcription_config"]
        self.assertEqual(config["language_codes"], ["uk-UA", "de-DE"])
        self.assertEqual(config["mode"]["timestamp_granularities"], ["word"])
        self.assertEqual(provider.client.interactions.kwargs["timeout"], 180)
        self.assertEqual(result["words"][0]["start"], 1.25)
        self.assertEqual(provider.client.files.deleted, ["files/1"])


if __name__ == "__main__":
    unittest.main()
