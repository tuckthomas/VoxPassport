"""Manifest-configured proxy driver for OpenAI-style speech backends."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from runtime.workers.tts_host.protocol import TtsDriver, TtsDriverRequest


_LANGUAGE_NAMES = {
    "ar": "Arabic", "cs": "Czech", "da": "Danish", "de": "German",
    "el": "Greek", "en": "English", "es": "Spanish", "fa": "Persian",
    "fi": "Finnish", "fr": "French", "he": "Hebrew", "hi": "Hindi",
    "hu": "Hungarian", "id": "Indonesian", "it": "Italian", "ja": "Japanese",
    "ko": "Korean", "ms": "Malay", "nl": "Dutch", "no": "Norwegian",
    "pl": "Polish", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian",
    "sv": "Swedish", "th": "Thai", "tl": "Tagalog", "tr": "Turkish",
    "vi": "Vietnamese", "zh": "Chinese",
}


class OpenAiSpeechProxyDriver(TtsDriver):
    """Reuse one driver for compatible HTTP TTS servers via manifest mapping."""

    def __init__(self, manifest) -> None:
        super().__init__(manifest)
        self._loaded = False

    def _options(self) -> dict:
        return self.manifest.driver_options

    def _backend_url(self) -> str:
        options = self._options()
        env_name = str(options.get("backend_url_env", "")).strip()
        if env_name and os.getenv(env_name):
            return str(os.environ[env_name]).rstrip("/")
        configured = str(options.get("backend_url", "")).strip()
        if configured:
            return configured.rstrip("/")
        raise RuntimeError(
            f"{self.manifest.display_name} has no backend endpoint. "
            "A supervisor-managed local endpoint or explicit remote backend URL is required."
        )

    def _health_url(self) -> str:
        return self._backend_url() + str(self._options().get("health_path", "/v1/models"))

    def load(self) -> None:
        try:
            req = urlrequest.Request(self._health_url(), method="GET")
            with urlrequest.urlopen(req, timeout=3) as response:
                if int(getattr(response, "status", 200)) >= 500:
                    raise RuntimeError(f"Backend health returned HTTP {response.status}")
            self._loaded = True
        except Exception as exc:
            self._loaded = False
            raise RuntimeError(
                f"{self.manifest.display_name} backend is not reachable at {self._backend_url()}"
            ) from exc

    def unload(self) -> None:
        options = self._options()
        unload_path = str(options.get("unload_path", "")).strip()
        if unload_path:
            try:
                req = urlrequest.Request(
                    self._backend_url() + unload_path,
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method=str(options.get("unload_method", "POST")).upper(),
                )
                with urlrequest.urlopen(req, timeout=float(options.get("unload_timeout_seconds", 15))):
                    pass
            except Exception:
                # A supervisor-managed local backend is terminated by the main
                # runtime after the driver unloads. Remote backends may simply
                # not expose an unload endpoint.
                pass
        self._loaded = False

    @staticmethod
    def _audio_data_uri(path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"Reference audio does not exist: {path}")
        return "data:audio/wav;base64," + base64.b64encode(path.read_bytes()).decode("ascii")

    def _language_value(self, language: str):
        mode = str(self._options().get("language_format", "code")).lower()
        if mode == "omit":
            return None
        if mode == "name":
            return _LANGUAGE_NAMES.get(language, language)
        return language

    def _encoded_reference_audio(self, path: Path) -> str:
        encoding = str(self._options().get("reference_audio_encoding", "data_uri"))
        return str(path.resolve()) if encoding == "path" else self._audio_data_uri(path)

    def _map_reference(self, payload: dict, request: TtsDriverRequest) -> None:
        if request.reference_audio is None:
            return
        options = self._options()
        mode = str(options.get("reference_mode", "flat")).lower()
        encoded = self._encoded_reference_audio(request.reference_audio)
        if mode == "references_array":
            item = {str(options.get("reference_audio_key", "audio_path")): encoded}
            text_key = str(options.get("reference_text_key", "text"))
            if text_key and request.reference_text:
                item[text_key] = request.reference_text
            payload[str(options.get("references_field", "references"))] = [item]
            return

        audio_field = str(options.get("reference_audio_field", "ref_audio"))
        payload[audio_field] = encoded
        transcript_field = options.get("reference_text_field", "ref_text")
        if transcript_field and request.reference_text:
            payload[str(transcript_field)] = request.reference_text

    def _payload(self, request: TtsDriverRequest, *, response_format: str, stream: bool) -> dict:
        options = self._options()
        payload = dict(options.get("static_payload", {}))
        if stream:
            payload.update(dict(options.get("stream_payload", {})))
        else:
            payload.update(dict(options.get("wav_payload", {})))
        payload[str(options.get("text_field", "input"))] = request.text
        payload[str(options.get("response_format_field", "response_format"))] = response_format
        stream_field = options.get("stream_field", "stream")
        if stream_field:
            payload[str(stream_field)] = bool(stream)

        language_field = options.get("language_field", "language")
        language_value = self._language_value(request.language)
        if language_field and language_value is not None:
            payload[str(language_field)] = language_value

        self._map_reference(payload, request)
        return payload

    def _post(self, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            self._backend_url() + str(self._options().get("speech_path", "/v1/audio/speech")),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            return urlrequest.urlopen(req, timeout=float(self._options().get("timeout_seconds", 300)))
        except urlerror.HTTPError as exc:
            self._loaded = False
            detail = exc.read(1500).decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{self.manifest.display_name} backend returned HTTP {exc.code}: {detail}"
            ) from exc
        except Exception as exc:
            self._loaded = False
            raise RuntimeError(
                f"{self.manifest.display_name} backend request failed: {exc}"
            ) from exc

    def synthesize_pcm(self, request: TtsDriverRequest):
        payload = self._payload(request, response_format="pcm", stream=True)
        carry = b""
        with self._post(payload) as response:
            while True:
                raw = response.read(32768)
                if not raw:
                    break
                data = carry + raw
                even = len(data) - (len(data) % 2)
                if even:
                    yield data[:even]
                carry = data[even:]

    def synthesize_wav(self, request: TtsDriverRequest) -> bytes:
        payload = self._payload(request, response_format="wav", stream=False)
        with self._post(payload) as response:
            body = response.read()
        if len(body) < 500:
            raise RuntimeError(f"{self.manifest.display_name} returned an unexpectedly small WAV payload")
        return body

    def health_check(self) -> bool:
        return self._loaded
