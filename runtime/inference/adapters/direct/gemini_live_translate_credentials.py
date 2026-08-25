"""Credential-resolver entrypoint for Gemini Live Translate.

The protocol/session implementation stays in ``gemini_live_translate``. This
entrypoint changes only credential acquisition so API keys can come from the OS
credential vault without being copied into process environment variables.
"""

from __future__ import annotations

from urllib.parse import urlencode

import aiohttp

from runtime.inference.adapters.direct.gemini_live_translate import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_MODEL_ID,
    DEFAULT_WEBSOCKET_URL,
    GeminiLiveTranslateError,
    GeminiLiveTranslateSession,
    GeminiLiveTranslateStrategy,
    _wait_for_setup_complete,
    build_gemini_setup_message,
)
from runtime.inference.provider_credentials import ProviderCredentialResolver
from runtime.inference.protocol import SampleFormat
from runtime.inference.translation_provider_catalog import (
    TranslationProviderCatalog,
    TranslationProviderDescriptor,
)
from runtime.inference.translation_session import (
    SpeechTranslationSession,
    SpeechTranslationSessionConfig,
)


class CredentialAwareGeminiLiveTranslateStrategy(GeminiLiveTranslateStrategy):
    def __init__(
        self,
        *,
        descriptor: TranslationProviderDescriptor | None = None,
        credential_resolver: ProviderCredentialResolver | None = None,
        model_id: str = DEFAULT_MODEL_ID,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        websocket_url: str = DEFAULT_WEBSOCKET_URL,
        echo_target_language: bool = True,
        setup_timeout_seconds: float = 20.0,
    ) -> None:
        super().__init__(
            model_id=model_id,
            api_key_env=api_key_env,
            websocket_url=websocket_url,
            echo_target_language=echo_target_language,
            setup_timeout_seconds=setup_timeout_seconds,
        )
        self._descriptor = descriptor or TranslationProviderCatalog().load().resolve(
            "gemini-3.5-live-translate"
        )
        self.credential_resolver = credential_resolver

    async def _resolved_api_key(self) -> str | None:
        if self.credential_resolver is not None:
            resolved = await self.credential_resolver.resolve(self._descriptor)
            if resolved is not None and resolved.secret.strip():
                return resolved.secret.strip()
        # Preserve existing automation/dev behavior when no vault key exists.
        import os
        value = os.getenv(self.api_key_env, "").strip()
        return value or None

    async def health_check(self) -> bool:
        return self._loaded and bool(await self._resolved_api_key())

    async def open_session(
        self,
        config: SpeechTranslationSessionConfig,
    ) -> SpeechTranslationSession:
        if not self._loaded:
            await self.load()
        if not await self.supports_language_pair(config.source_language, config.target_language):
            raise GeminiLiveTranslateError(
                "Gemini Live Translate language pair is not confirmed by this manifest: "
                f"{config.source_language.value}->{config.target_language.value}"
            )
        if config.input_sample_format != SampleFormat.PCM_S16LE or config.input_channels != 1:
            raise GeminiLiveTranslateError("Gemini adapter requires mono PCM_S16LE input")

        api_key = await self._resolved_api_key()
        if not api_key:
            raise GeminiLiveTranslateError("Gemini API key is not configured")

        client = aiohttp.ClientSession()
        websocket = None
        try:
            query = urlencode({"key": api_key})
            websocket = await client.ws_connect(
                f"{self.websocket_url}?{query}",
                heartbeat=30,
                max_msg_size=16 * 1024 * 1024,
            )
            await websocket.send_json(build_gemini_setup_message(
                config,
                model_id=self.model_id,
                echo_target_language=self.echo_target_language,
            ))
            await _wait_for_setup_complete(
                websocket,
                timeout_seconds=self.setup_timeout_seconds,
            )
            session = GeminiLiveTranslateSession(
                config,
                websocket=websocket,
                http_session=client,
            )
            await session.start()
            return session
        except Exception as exc:
            if websocket is not None:
                await websocket.close()
            await client.close()
            if isinstance(exc, GeminiLiveTranslateError):
                raise
            # aiohttp errors may include the full request URL; never forward the
            # provider URL because its query string contains the resolved key.
            raise GeminiLiveTranslateError(
                f"Gemini Live Translate connection/setup failed ({type(exc).__name__})"
            ) from None
