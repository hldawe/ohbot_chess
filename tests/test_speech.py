# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Speech output.

The interesting assertions are about the WAV, because the library's lip sync
reads it directly and has two undocumented requirements. Getting either wrong
does not fail loudly -- it either crashes on a short reply or moves the mouth
wrongly, both of which are hard to trace back to here.
"""

from __future__ import annotations

import sys
import types
import wave
from typing import Any

import pytest

from ohbot_chess import config, speech

# -- a fake Piper -----------------------------------------------------------


class FakeChunk:
    """One AudioChunk, as piper-tts >= 1.3 yields them."""

    def __init__(self, data: bytes, width: int = 2, channels: int = 1) -> None:
        self.audio_int16_bytes = data
        self.sample_width = width
        self.sample_channels = channels


class FakeVoice:
    """Stands in for a loaded Piper voice.

    Shaped after the piper-tts >= 1.3 API: synthesize() yields AudioChunk
    objects. The 1.1/1.2 API took a wave writer and is not supported, because
    those versions cannot be installed on macOS at all.
    """

    def __init__(self, rate: int = 22050, seconds: float = 0.05) -> None:
        self.config = types.SimpleNamespace(sample_rate=rate)
        self.seconds = seconds
        self.rate = rate
        self.width = 2
        self.channels = 1
        self.texts: list[str] = []
        self.configs: list[Any] = []

    def synthesize(self, text: str, syn_config: Any = None, **kwargs: Any) -> Any:
        self.texts.append(text)
        self.configs.append(syn_config)
        # Two chunks, because the real engine streams and the code has to
        # join them rather than taking the first.
        half = b"\x10\x00" * int(self.rate * self.seconds / 2)
        yield FakeChunk(half, self.width, self.channels)
        yield FakeChunk(half, self.width, self.channels)


@pytest.fixture
def piper_installed(monkeypatch: Any) -> FakeVoice:
    """Install a fake piper.voice module and a fake voice on disk."""
    voice = FakeVoice()
    package = types.ModuleType("piper")
    package.PiperVoice = types.SimpleNamespace(  # type: ignore[attr-defined]
        load=lambda *a, **k: voice
    )
    config_module = types.ModuleType("piper.config")

    class SynthesisConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    config_module.SynthesisConfig = SynthesisConfig  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "piper", package)
    monkeypatch.setitem(sys.modules, "piper.config", config_module)
    return voice


@pytest.fixture
def voice_dir(tmp_path: Any) -> str:
    directory = tmp_path / "voices"
    directory.mkdir()
    (directory / f"{config.DEFAULT_VOICE}.onnx").write_bytes(b"fake")
    (directory / f"{config.DEFAULT_VOICE}.onnx.json").write_text("{}")
    return str(directory)


# -- discovery --------------------------------------------------------------


def test_voice_files_are_a_pair() -> None:
    model, meta = speech.voice_files("en_GB-alba-medium", "voices")
    assert model.endswith(".onnx")
    assert meta == model + ".json"


def test_missing_voice_is_reported_not_guessed(tmp_path: Any) -> None:
    assert not speech.available("nope", str(tmp_path))
    assert len(speech.missing("nope", str(tmp_path))) == 2


def test_missing_voice_raises_something_actionable(tmp_path: Any) -> None:
    with pytest.raises(speech.VoiceUnavailable) as excinfo:
        speech.PiperTTS("nope", str(tmp_path))
    assert "Missing Piper voice files" in str(excinfo.value)


# -- the WAV constraints ----------------------------------------------------


def test_wav_is_sixteen_bit_mono(piper_installed: FakeVoice, voice_dir: str, tmp_path: Any) -> None:
    """The viseme loop indexes buffer[i] + buffer[i+1]*256.

    Anything other than 16-bit PCM makes the mouth move to the wrong envelope,
    which looks like a lip-sync bug rather than a format bug.
    """
    target = str(tmp_path / "speech.wav")
    speech.PiperTTS(config.DEFAULT_VOICE, voice_dir).synth("Check.", target)

    with wave.open(target) as handle:
        assert handle.getsampwidth() == 2
        assert handle.getnchannels() == 1


def test_short_clips_get_a_silent_tail(
    piper_installed: FakeVoice, voice_dir: str, tmp_path: Any
) -> None:
    """say() loops range(0, length - chunk, chunk) and then indexes times[-1].

    Audio under about 0.2s leaves that list empty and raises IndexError.
    "Check." is a realistic thing for a chess robot to say, so every clip is
    padded rather than hoping replies are long.
    """
    piper_installed.seconds = 0.02  # far shorter than one viseme chunk
    target = str(tmp_path / "short.wav")
    speech.PiperTTS(config.DEFAULT_VOICE, voice_dir).synth("Check.", target)

    with wave.open(target) as handle:
        duration = handle.getnframes() / handle.getframerate()
    assert duration >= config.TAIL_SILENCE_SECONDS


def test_tail_is_actually_silent(piper_installed: FakeVoice, voice_dir: str, tmp_path: Any) -> None:
    target = str(tmp_path / "tail.wav")
    speech.PiperTTS(config.DEFAULT_VOICE, voice_dir).synth("Check.", target)

    with wave.open(target) as handle:
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    tail_bytes = int(rate * config.TAIL_SILENCE_SECONDS) * 2
    assert set(frames[-tail_bytes:]) == {0}


def test_sample_rate_follows_the_voice(
    piper_installed: FakeVoice, voice_dir: str, tmp_path: Any
) -> None:
    piper_installed.config.sample_rate = 16000
    piper_installed.rate = 16000
    target = str(tmp_path / "rate.wav")
    speech.PiperTTS(config.DEFAULT_VOICE, voice_dir).synth("Hello.", target)

    with wave.open(target) as handle:
        assert handle.getframerate() == 16000


def test_all_chunks_are_joined(piper_installed: FakeVoice, voice_dir: str, tmp_path: Any) -> None:
    """The engine streams. Taking the first chunk truncates every utterance."""
    target = str(tmp_path / "chunks.wav")
    speech.PiperTTS(config.DEFAULT_VOICE, voice_dir).synth("Knight to f three.", target)

    with wave.open(target) as handle:
        rate = handle.getframerate()
        duration = handle.getnframes() / rate
    expected = piper_installed.seconds + config.TAIL_SILENCE_SECONDS
    assert duration == pytest.approx(expected, abs=0.01)


def test_wrong_audio_format_is_refused_loudly(
    piper_installed: FakeVoice, voice_dir: str, tmp_path: Any
) -> None:
    """A width mismatch does not fail on its own -- it moves the mouth wrongly.

    The viseme loop reads the WAV directly and assumes 16-bit mono, so a voice
    at a different width produces a plausible-looking but wrong envelope. That
    is far harder to trace than an exception here.
    """
    piper_installed.width = 4
    with pytest.raises(speech.VoiceUnavailable, match="16-bit mono"):
        speech.PiperTTS(config.DEFAULT_VOICE, voice_dir).synth("Hi.", str(tmp_path / "x.wav"))


def test_speaking_rate_is_passed_through(
    piper_installed: FakeVoice, voice_dir: str, tmp_path: Any
) -> None:
    engine = speech.PiperTTS(config.DEFAULT_VOICE, voice_dir, length_scale=1.2)
    engine.synth("Hello.", str(tmp_path / "rate.wav"))
    assert piper_installed.configs[-1].length_scale == 1.2


def test_no_rate_override_leaves_the_voice_default(
    piper_installed: FakeVoice, voice_dir: str, tmp_path: Any
) -> None:
    engine = speech.PiperTTS(config.DEFAULT_VOICE, voice_dir)
    engine.synth("Hello.", str(tmp_path / "rate.wav"))
    assert piper_installed.configs[-1] is None


def test_text_reaches_the_engine(piper_installed: FakeVoice, voice_dir: str, tmp_path: Any) -> None:
    speech.PiperTTS(config.DEFAULT_VOICE, voice_dir).synth(
        "Knight to f three.", str(tmp_path / "a.wav")
    )
    assert piper_installed.texts == ["Knight to f three."]


# -- installation -----------------------------------------------------------


def test_install_rebinds_the_generator(
    piper_installed: FakeVoice, voice_dir: str, fake_ohbot: Any
) -> None:
    """say() resolves _generateSpeechFile as a module global at call time.

    So rebinding the attribute is the whole integration -- no fork of the
    library, and viseme calculation, threading and playback keep working.
    """
    original = fake_ohbot._generateSpeechFile
    engine = speech.PiperTTS(config.DEFAULT_VOICE, voice_dir)
    speech.install(engine, fake_ohbot)
    try:
        assert fake_ohbot._generateSpeechFile == engine.synth
        assert fake_ohbot._generateSpeechFile != original
    finally:
        speech.uninstall(fake_ohbot)


def test_uninstall_restores_the_builtin(
    piper_installed: FakeVoice, voice_dir: str, fake_ohbot: Any
) -> None:
    original = fake_ohbot._generateSpeechFile
    engine = speech.PiperTTS(config.DEFAULT_VOICE, voice_dir)
    speech.install(engine, fake_ohbot)
    speech.uninstall(fake_ohbot)
    assert fake_ohbot._generateSpeechFile == original


def test_synth_signature_matches_the_library(piper_installed: FakeVoice, voice_dir: str) -> None:
    """It has to stand in for _generateSpeechFile(text) directly."""
    import inspect

    engine = speech.PiperTTS(config.DEFAULT_VOICE, voice_dir)
    parameters = list(inspect.signature(engine.synth).parameters)
    assert parameters[0] == "text"
    assert all(
        inspect.signature(engine.synth).parameters[p].default is not inspect.Parameter.empty
        for p in parameters[1:]
    )
