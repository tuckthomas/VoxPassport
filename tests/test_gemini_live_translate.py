import base64

import pytest

from runtime.inference.adapters.direct import gemini_live_translate as gemini
from runtime.inference.protocol import AudioFrame, LanguageCode, SampleFormat
from runtime.inference.translation_session import (
    SpeechTranslationEventType,
    SpeechTranslationOutputMode,
    SpeechTranslationSessionConfig,
    SpeechTranslationSessionState,
)


def _config(
    *,
    output_mode: SpeechTranslationOutputMode = SpeechTranslationOutputMode.TEXT_AND_AUDIO,
    request_source_transcript: bool = True,
) -> SpeechTranslationSessionConfig:
    return SpeechTranslationSessionConfig(
        source_language=LanguageCode.EN,
        target_language=LanguageCode.RO,
        input_sample_rate_hz=16000,
        input_channels=1,
        input_sample_format=SampleFormat.PCM_S16LE,
        output_mode=output_mode,
        request_source_transcript=request_source_transcript,
    )


def _frame(data: bytes = b"\x01\x02\x03\x04") -> AudioFrame:
    return AudioFrame(
        stream_id="mic",
        sequence=0,
        monotonic_timestamp_ns=1,
        sample_rate_hz=16000,
        channels=1,
        sample_format=SampleFormat.PCM_S16LE,
        data=data,
    )


def test_setup_message_requests_audio_translation_and_transcripts():
    payload = gemini.build_gemini_setup_message(_config())
    setup = payload["setup"]
    generation = setup["generationConfig"]

    assert setup["model"] == "models/gemini-3.5-live-translate-preview"
    assert generation["responseModalities"] == ["AUDIO"]
    assert generation["translationConfig"] == {
        "targetLanguageCode": "ro",
        "echoTargetLanguage": True,
    }
    assert generation["inputAudioTranscription"] == {}
    assert generation["outputAudioTranscription"] == {}


def test_setup_message_omits_optional_transcriptions_when_not_requested():
    payload = gemini.build_gemini_setup_message(_config(
        output_mode=SpeechTranslationOutputMode.TRANSLATED_AUDIO,
        request_source_transcript=False,
    ))
    generation = payload["setup"]["generationConfig"]

    assert "inputAudioTranscription" not in generation
    assert "outputAudioTranscription" not in generation


def test_audio_message_base64_encodes_pcm_and_declares_sample_rate():
    frame = _frame()
    payload = gemini.build_gemini_audio_message(frame)
    audio = payload["realtimeInput"]["audio"]

    assert audio["mimeType"] == "audio/pcm;rate=16000"
    assert base64.b64decode(audio["data"]) == frame.data


def test_audio_message_rejects_non_mono_or_non_s16_input():
    stereo = _frame()
    stereo.channels = 2
    with pytest.raises(gemini.GeminiLiveTranslateError, match="mono"):
        gemini.build_gemini_audio_message(stereo)

    float_frame = _frame()
    float_frame.sample_format = SampleFormat.PCM_F32LE
    with pytest.raises(gemini.GeminiLiveTranslateError, match="PCM_S16LE"):
        gemini.build_gemini_audio_message(float_frame)


def test_server_message_maps_transcripts_and_24khz_audio():
    audio_bytes = b"\x10\x20\x30\x40"
    payload = {
        "serverContent": {
            "inputTranscription": {"text": "hello"},
            "outputTranscription": {"text": "salut"},
            "modelTurn": {
                "parts": [{
                    "inlineData": {
                        "mimeType": "audio/pcm;rate=24000",
                        "data": base64.b64encode(audio_bytes).decode("ascii"),
                    }
                }]
            },
        }
    }

    events = gemini.map_gemini_server_message(
        payload,
        emit_source_text=True,
        emit_translation_text=True,
        emit_audio=True,
        audio_sequence=7,
    )

    assert [event.event_type for event in events] == [
        SpeechTranslationEventType.SOURCE_PARTIAL,
        SpeechTranslationEventType.TRANSLATION_PARTIAL,
        SpeechTranslationEventType.TRANSLATED_AUDIO,
    ]
    assert events[0].text == "hello"
    assert events[1].text == "salut"
    assert events[2].audio.sequence == 7
    assert events[2].audio.sample_rate_hz == 24000
    assert events[2].audio.sample_format == SampleFormat.PCM_S16LE
    assert events[2].audio.data == audio_bytes


def test_interruption_and_goaway_map_to_transport_neutral_events():
    events = gemini.map_gemini_server_message(
        {
            "serverContent": {"interrupted": True},
            "goAway": {"timeLeft": "10s"},
        },
        emit_source_text=True,
        emit_translation_text=True,
        emit_audio=True,
        audio_sequence=0,
    )

    assert events[0].event_type == SpeechTranslationEventType.STATE
    assert events[0].state == SpeechTranslationSessionState.LISTENING
    assert events[0].metadata["flush_playback"] is True
    assert events[1].event_type == SpeechTranslationEventType.ERROR
    assert events[1].error_code == "provider_go_away"
    assert events[1].recoverable is True


@pytest.mark.asyncio
async def test_strategy_language_pair_is_manifest_driven():
    strategy = gemini.GeminiLiveTranslateStrategy()
    assert await strategy.supports_language_pair(LanguageCode.EN, LanguageCode.RO)
    assert await strategy.supports_language_pair(LanguageCode.RO, LanguageCode.EN)
    assert not await strategy.supports_language_pair(LanguageCode.EN, LanguageCode.EN)
    assert not await strategy.supports_language_pair(LanguageCode.EN, LanguageCode.FR)


@pytest.mark.asyncio
async def test_connection_failure_does_not_expose_api_key(monkeypatch):
    secret = "super-secret-api-key"
    monkeypatch.setenv("GEMINI_API_KEY", secret)

    class FakeClientSession:
        async def ws_connect(self, url, **_kwargs):
            raise RuntimeError(f"failed connection URL={url}")

        async def close(self):
            return None

    monkeypatch.setattr(gemini.aiohttp, "ClientSession", FakeClientSession)
    strategy = gemini.GeminiLiveTranslateStrategy()

    with pytest.raises(gemini.GeminiLiveTranslateError) as caught:
        await strategy.open_session(_config())

    assert secret not in str(caught.value)
    assert "RuntimeError" in str(caught.value)
