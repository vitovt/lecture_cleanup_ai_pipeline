import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from stt_api.errors import ProviderError, ProviderRequestError
from stt_api.providers.elevenlabs import ElevenLabsProvider


class FakeSpeechToText:
    def __init__(self):
        self.kwargs = None

    def convert(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            text="Привіт Halbleiter",
            language_code="ukr",
            language_probability=0.91,
            words=[
                SimpleNamespace(
                    type="word", text="Привіт", start=0.1, end=0.5,
                    speaker_id="speaker_0",
                ),
                SimpleNamespace(
                    type="spacing", text=" ", start=0.5, end=0.51,
                    speaker_id="speaker_0",
                ),
                SimpleNamespace(
                    type="word", text="Halbleiter", start=0.51, end=1.1,
                    speaker_id="speaker_1",
                ),
            ],
        )


class FakeClient:
    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.speech_to_text = FakeSpeechToText()


class FailingSpeechToText:
    status_code = 400
    message = "invalid audio"

    def convert(self, **_kwargs):
        error = RuntimeError(self.message)
        error.status_code = self.status_code
        raise error


class FailingClient(FakeClient):
    speech_type = FailingSpeechToText

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.speech_to_text = self.speech_type()


class AuthFailingSpeechToText(FailingSpeechToText):
    status_code = 401
    message = "invalid API key"


class AuthFailingClient(FailingClient):
    speech_type = AuthFailingSpeechToText


class ElevenLabsProviderTests(unittest.TestCase):
    def _provider(self, client_factory=FakeClient):
        return ElevenLabsProvider(
            "secret", attempts=1, initial_delay=0, multiplier=1, max_delay=0,
            jitter=0, request_timeout=240, tag_audio_events=False,
            client_factory=client_factory,
        )

    def _audio(self, directory):
        path = Path(directory) / "audio.mp3"
        path.write_bytes(b"test audio")
        return path

    def test_multilingual_request_uses_auto_detection_and_keyterms(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = self._provider()
            result = provider.transcribe(
                self._audio(directory), model="scribe_v2",
                language_codes=["uk-UA", "de-DE"], vocabulary=["Halbleiter"],
                mode="verbatim", timestamps=True, diarization=True,
            )
        request = provider.client.speech_to_text.kwargs
        self.assertNotIn("language_code", request)
        self.assertEqual(request["keyterms"], ["Halbleiter"])
        self.assertEqual(request["timestamps_granularity"], "word")
        self.assertTrue(request["diarize"])
        self.assertFalse(request["no_verbatim"])
        self.assertEqual(result["language_code"], "ukr")
        self.assertEqual([word["text"] for word in result["words"]], ["Привіт", "Halbleiter"])

    def test_single_language_is_reduced_to_iso_639_base(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = self._provider()
            result = provider.transcribe(
                self._audio(directory), model="scribe_v2",
                language_codes=["de-DE"], vocabulary=[], mode="smart",
                timestamps=False, diarization=False,
            )
        request = provider.client.speech_to_text.kwargs
        self.assertEqual(request["language_code"], "de")
        self.assertEqual(request["timestamps_granularity"], "none")
        self.assertTrue(request["no_verbatim"])
        self.assertNotIn("keyterms", request)
        self.assertEqual(result["words"], [])

    def test_bad_audio_is_a_file_scoped_failure(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ProviderRequestError):
            self._provider(FailingClient).transcribe(
                self._audio(directory), model="scribe_v2", language_codes=[],
                vocabulary=[], mode="verbatim", timestamps=True, diarization=False,
            )

    def test_authentication_is_a_provider_wide_failure(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ProviderError):
            self._provider(AuthFailingClient).transcribe(
                self._audio(directory), model="scribe_v2", language_codes=[],
                vocabulary=[], mode="verbatim", timestamps=True, diarization=False,
            )


if __name__ == "__main__":
    unittest.main()
