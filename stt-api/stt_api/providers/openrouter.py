"""OpenRouter's dedicated transcription API, normalized for the STT pipeline."""
from __future__ import annotations

import base64
import http.client
from copy import deepcopy
import json
import logging
import math
from pathlib import Path
import random
import time
from urllib import error, request

from accounting.usage import request_with_usage, response_json

from ..errors import ConfigError, InputError, ProviderError, ProviderRequestError, RetryExhaustedError

LOG = logging.getLogger('stt-api')


class OpenRouterProvider:
    def __init__(self, api_key, *, attempts, initial_delay, multiplier, max_delay,
                 jitter, request_timeout, api_base_url='https://openrouter.ai/api/v1',
                 provider_options=None, max_audio_bytes=25 * 1024 * 1024,
                 sleeper=time.sleep):
        if provider_options is not None and not isinstance(provider_options, dict):
            raise ConfigError('providers.openrouter.provider_options must be a mapping or null')
        if type(max_audio_bytes) is not int or max_audio_bytes < 1:
            raise ConfigError('providers.openrouter.request.max_audio_bytes must be a positive integer')
        try:
            json.dumps(provider_options, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ConfigError('OpenRouter provider_options must contain JSON values') from exc
        self.api_key = api_key
        self.endpoint = api_base_url.rstrip('/') + '/audio/transcriptions'
        self.provider_options = deepcopy(provider_options)
        self.max_audio_bytes = max_audio_bytes
        self.attempts = attempts
        self.initial_delay = initial_delay
        self.multiplier = multiplier
        self.max_delay = max_delay
        self.jitter = jitter
        self.request_timeout = request_timeout
        self.sleeper = sleeper

    @staticmethod
    def _normalize(response, *, timestamps, diarization):
        if not isinstance(response, dict) or not isinstance(response.get('text'), str):
            raise ProviderRequestError('OpenRouter returned no transcription text')
        words = []
        if timestamps or diarization:
            raw_words = response.get('words')
            if raw_words is None and not response['text'].strip():
                raw_words = []
            if not isinstance(raw_words, list) or (response['text'].strip() and not raw_words):
                raise ProviderRequestError('OpenRouter model returned no word timestamps; use a compatible model or --timestamps off')
            for item in raw_words:
                if not isinstance(item, dict):
                    raise ProviderRequestError('OpenRouter returned malformed word timestamps')
                start, end = item.get('start'), item.get('end')
                text = item.get('word', item.get('text'))
                if (not isinstance(text, str) or not text.strip() or
                    type(start) not in (int, float) or type(end) not in (int, float) or
                    not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start):
                    raise ProviderRequestError('OpenRouter returned malformed word timestamps')
                words.append({'text': text.strip(), 'start': float(start), 'end': float(end),
                              'speaker': item.get('speaker_label') if item.get('speaker_label') is not None else item.get('speaker')})
        if diarization and words and all(word['speaker'] is None for word in words):
            raise ProviderRequestError('OpenRouter model returned no speaker labels; use a compatible model or --diarization off')
        return {'text': response['text'].strip(), 'words': words,
                'language_code': str(response.get('language') or ''),
                'usage': response.get('usage'), 'raw_response': response}

    def transcribe(self, path: Path, *, model, language_codes, vocabulary,
                   mode, timestamps, diarization):
        if mode != 'verbatim':
            raise InputError('OpenRouter STT does not expose a generic smart mode; use verbatim')
        if path.stat().st_size > self.max_audio_bytes:
            raise InputError('OpenRouter audio part exceeds request.max_audio_bytes; reduce providers.openrouter.chunking.max_seconds')
        audio_format = path.suffix.lower().lstrip('.')
        if audio_format not in {'wav', 'mp3', 'flac', 'm4a', 'ogg', 'aac', 'webm', 'mp4'}:
            raise InputError('OpenRouter audio format is unsupported; convert the input to FLAC, WAV or MP3')
        payload = {'model': model, 'input_audio': {
            'data': base64.b64encode(path.read_bytes()).decode('ascii'), 'format': audio_format},
            'response_format': 'verbose_json' if timestamps or diarization else 'json'}
        if timestamps or diarization:
            payload['timestamp_granularities'] = ['word']
        if diarization:
            payload['diarize'] = True
        if len(language_codes) == 1:
            payload['language'] = language_codes[0].split('-', 1)[0].lower()
        if vocabulary:
            payload['keyterms'] = vocabulary
        if self.provider_options is not None:
            payload['provider'] = deepcopy(self.provider_options)
        data = json.dumps(payload, allow_nan=False).encode()
        # Audio bytes and credentials are deliberately excluded even at TRACE.
        LOG.log(5, 'OpenRouter STT request: %s', {k: v for k, v in payload.items() if k != 'input_audio'})
        for attempt in range(self.attempts):
            try:
                req = request.Request(self.endpoint, data=data, method='POST', headers={
                    'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json',
                    'Accept': 'application/json', 'User-Agent': 'lecture-cleanup-pipeline/1.0'})
                def send():
                    with request.urlopen(req, timeout=self.request_timeout) as response:
                        try:
                            return response_json(response.read())
                        except (ValueError, UnicodeError) as exc:
                            raise ProviderRequestError('OpenRouter returned invalid transcription JSON') from exc
                parsed = request_with_usage(send, scope='stt', provider='openrouter', model=model,
                    attempt=attempt + 1, attempts=self.attempts, currency='USD', emit=LOG.info, visible=LOG.isEnabledFor(logging.INFO))
                if isinstance(parsed, dict) and isinstance(parsed.get('error'), dict):
                    code = parsed['error'].get('code')
                    if type(code) is int:
                        raise error.HTTPError(self.endpoint, code, 'OpenRouter error', {}, None)
                    raise ProviderRequestError('OpenRouter rejected transcription')
                return self._normalize(parsed, timestamps=timestamps, diarization=diarization)
            except error.HTTPError as exc:
                status = exc.code
                exc.close()
                if status not in {408, 409, 429, 500, 502, 503, 504, 520, 522, 524, 529}:
                    cls = ProviderError if status in {401, 402, 403, 404} else ProviderRequestError
                    raise cls(f'OpenRouter transcription failed (HTTP {status})') from exc
            except (error.URLError, http.client.HTTPException, ConnectionError, TimeoutError, OSError):
                status = 'connection'
            if attempt + 1 == self.attempts:
                raise RetryExhaustedError(f'OpenRouter transcription failed after {self.attempts} attempts (status={status})')
            delay = min(self.max_delay, self.initial_delay * self.multiplier ** attempt)
            delay += random.uniform(0, max(0.0, self.jitter))
            LOG.warning('openrouter: attempt %d/%d failed (status=%s); retrying in %.1fs',
                        attempt + 1, self.attempts, status, delay)
            self.sleeper(delay)
        raise ConfigError('processing.retry.attempts must be at least 1')
