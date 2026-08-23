from dataclasses import replace

import pytest

from runtime.inference.protocol import LanguageCode, SampleFormat
from runtime.inference.translation_session import (
    SpeechTranslationEvent,
    SpeechTranslationEventType,
    SpeechTranslationOutputMode,
    SpeechTranslationSessionConfig,
    SpeechTranslationSessionState,
    TranslatedAudioChunk,
)


def test_session_config_rejects_same_language_and_invalid_audio_shape():
    with pytest.raises(ValueError, match="must differ"):
        SpeechTranslationSessionConfig(
            source_language=LanguageCode.EN,
            target_language=LanguageCode.EN,
            input_sample_rate_hz=16000,
        )

    with pytest.raises(ValueError, match="sample_rate"):
        SpeechTranslationSessionConfig(
            source_language=LanguageCode.EN,
            target_language=LanguageCode.RO,
            input_sample_rate_hz=0,
        )


def test_session_config_supports_direct_audio_output_and_optional_voice_profile():
    config = SpeechTranslationSessionConfig(
        source_language=LanguageCode.EN,
        target_language=LanguageCode.RO,
        input_sample_rate_hz=48000,
        input_channels=2,
        output_mode=SpeechTranslationOutputMode.TEXT_AND_AUDIO,
        voice_profile_id="family-speaker",
    )

    assert config.output_mode == SpeechTranslationOutputMode.TEXT_AND_AUDIO
    assert config.voice_profile_id == "family-speaker"


def test_text_events_require_text():
    with pytest.raises(ValueError, match="requires text"):
        SpeechTranslationEvent(
            event_type=SpeechTranslationEventType.TRANSLATION_FINAL,
            sequence=1,
        )

    event = SpeechTranslationEvent(
        event_type=SpeechTranslationEventType.TRANSLATION_FINAL,
        sequence=1,
        text="Bună ziua",
    )
    assert event.text == "Bună ziua"


def test_translated_audio_event_requires_audio_chunk():
    with pytest.raises(ValueError, match="requires an audio chunk"):
        SpeechTranslationEvent(
            event_type=SpeechTranslationEventType.TRANSLATED_AUDIO,
            sequence=0,
        )

    chunk = TranslatedAudioChunk(
        sequence=0,
        sample_rate_hz=24000,
        channels=1,
        sample_format=SampleFormat.PCM_S16LE,
        data=b"\x00\x00",
        is_final_chunk=True,
    )
    event = SpeechTranslationEvent(
        event_type=SpeechTranslationEventType.TRANSLATED_AUDIO,
        sequence=0,
        audio=chunk,
    )
    assert event.audio is chunk


def test_state_and_error_events_enforce_required_fields():
    with pytest.raises(ValueError, match="requires state"):
        SpeechTranslationEvent(
            event_type=SpeechTranslationEventType.STATE,
            sequence=0,
        )

    state = SpeechTranslationEvent(
        event_type=SpeechTranslationEventType.STATE,
        sequence=0,
        state=SpeechTranslationSessionState.READY,
    )
    assert state.state == SpeechTranslationSessionState.READY

    with pytest.raises(ValueError, match="requires error_code"):
        SpeechTranslationEvent(
            event_type=SpeechTranslationEventType.ERROR,
            sequence=1,
        )

    error = SpeechTranslationEvent(
        event_type=SpeechTranslationEventType.ERROR,
        sequence=1,
        error_code="provider_closed",
        recoverable=True,
    )
    assert error.recoverable is True
