# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Speech output: Piper, standing in for the built-in voice.

WHY THIS IS ONLY A SUBSTITUTION

ohbot.say() looks like it does synthesis and lip sync together, so swapping the
voice ought to cost the lip movement. It doesn't -- on macOS the lip sync is
driven by LOUDNESS, not phonemes. say() opens the generated WAV, sums the
sample bytes in chunks of framerate/10, normalises to 0-10, and feeds that
envelope to the lip motor. Real phoneme data is used only on Raspberry Pi.

So anything that writes a valid WAV where the library expects one gets lip sync
for free. Replacing _generateSpeechFile is the entire integration: viseme
calculation, threading, playback and untilDone all keep working untouched.

TWO CONSTRAINTS come from that same envelope code:

  * It indexes buffer[i] + buffer[i+1]*256, so the WAV must be 16-bit PCM.
    Piper emits exactly that, so unlike a float32 engine there is nothing to
    convert -- this is the one respect in which Piper is the easier fit.
  * It loops range(0, length - chunk, chunk) and then indexes times[-1]. Audio
    under about 0.2s leaves that list empty and say() raises IndexError.
    "Check." is a realistic utterance, so every clip gets a silent tail.

WHY PIPER AND NOT A FASTER ENGINE

Voice consistency across robots. The Scottish voice is the same one the Reachy
build uses; the alternatives have no Scottish voice at all, only RP. Two heads
with one voice read as one system.

WHICH PIPER

Development moved from rhasspy/piper (MIT, archived October 2025) to
OHF-Voice/piper1-gpl (GPL-3.0-or-later). Require **piper-tts >= 1.3.0**.

That is not a preference. Versions 1.1 and 1.2 depend on a separate
piper-phonemize package that has no macOS wheel, so `pip install piper-tts`
simply fails on a Mac. From 1.3.0 espeak-ng is embedded and the dependency is
gone. The API changed at the same time: `synthesize()` now yields AudioChunk
objects rather than raw bytes.
"""

from __future__ import annotations

import os
import wave
from typing import Any

from . import config


class VoiceUnavailable(RuntimeError):
    """Raised when the Piper voice files are missing or unloadable."""


def voice_files(voice: str = config.DEFAULT_VOICE, directory: str = "voices") -> tuple[str, str]:
    """The (.onnx, .onnx.json) pair for a named voice."""
    model = os.path.join(directory, f"{voice}.onnx")
    return model, model + ".json"


def available(voice: str = config.DEFAULT_VOICE, directory: str = "voices") -> bool:
    return all(os.path.exists(p) for p in voice_files(voice, directory))


def missing(voice: str = config.DEFAULT_VOICE, directory: str = "voices") -> list[str]:
    return [p for p in voice_files(voice, directory) if not os.path.exists(p)]


class PiperTTS:
    """Renders Ohbot's speech WAV with Piper."""

    def __init__(
        self,
        voice: str = config.DEFAULT_VOICE,
        directory: str = "voices",
        length_scale: float | None = None,
    ) -> None:
        model, config_file = voice_files(voice, directory)
        if not os.path.exists(model) or not os.path.exists(config_file):
            raise VoiceUnavailable(
                "Missing Piper voice files: {}\nRun: python tools/fetch_voice.py".format(
                    ", ".join(missing(voice, directory))
                )
            )
        # Imported here so this module can be probed for availability, and
        # imported in tests, without paying for the ONNX runtime.
        try:
            from piper import PiperVoice
        except ImportError as e:  # pragma: no cover - depends on install
            raise VoiceUnavailable("piper-tts is not installed. Run: pip install piper-tts") from e

        self.voice_name = voice
        self.length_scale = length_scale
        self._voice: Any = PiperVoice.load(model, config_path=config_file)

    @property
    def sample_rate(self) -> int:
        try:
            return int(self._voice.config.sample_rate)
        except Exception:  # pragma: no cover - version differences
            return 22050

    def _synthesis_config(self) -> Any:
        """Speaking-rate override, or None to use the voice's own default."""
        if self.length_scale is None:
            return None
        try:
            from piper.config import SynthesisConfig
        except ImportError:  # pragma: no cover - older piper
            return None
        return SynthesisConfig(length_scale=self.length_scale)

    def _pcm(self, text: str) -> bytes:
        """Raw 16-bit mono PCM for the text.

        `synthesize()` yields AudioChunk objects, each of which exposes
        `audio_int16_bytes` -- which is precisely the format the viseme loop
        needs, so there is no conversion step here at all.

        Chunks are asserted to be 16-bit mono rather than assumed. A voice that
        came back at a different width would not fail loudly; it would move the
        mouth to the wrong envelope, which is a maddening thing to trace back
        to a format mismatch.
        """
        pieces: list[bytes] = []
        for chunk in self._voice.synthesize(text, self._synthesis_config()):
            width = getattr(chunk, "sample_width", 2)
            channels = getattr(chunk, "sample_channels", 1)
            if width != 2 or channels != 1:
                raise VoiceUnavailable(
                    f"{self.voice_name} produced {width * 8}-bit audio on "
                    f"{channels} channel(s); the lip sync needs 16-bit mono."
                )
            pieces.append(chunk.audio_int16_bytes)
        return b"".join(pieces)

    def synth(self, text: str, path: str | None = None) -> str:
        """Render text to the WAV the ohbot library expects.

        Signature is compatible with ohbot._generateSpeechFile(text) so it can
        stand in for it directly.
        """
        target = path or _speech_path()
        pcm = self._pcm(text)

        rate = self.sample_rate
        tail = b"\x00\x00" * int(rate * config.TAIL_SILENCE_SECONDS)

        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with wave.open(target, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)  # 16-bit, required by the viseme loop
            writer.setframerate(rate)
            writer.writeframes(pcm + tail)
        return target


def _speech_path() -> str:
    try:
        from ohbot import ohbot

        return str(ohbot.speechAudioFile)
    except Exception:  # pragma: no cover - no library present
        return os.path.join("ohbotData", "ohbotspeech.wav")


_original: Any = None


def install(engine: PiperTTS, ohbot_module: Any = None) -> PiperTTS:
    """Route ohbot.say() through Piper.

    say() looks _generateSpeechFile up as a module global at call time, so
    rebinding the attribute is enough -- no fork, no patch to the library.
    """
    global _original
    if ohbot_module is None:
        from ohbot import ohbot as ohbot_module  # type: ignore[no-redef]
    if _original is None:
        _original = ohbot_module._generateSpeechFile
    ohbot_module._generateSpeechFile = engine.synth
    return engine


def uninstall(ohbot_module: Any = None) -> None:
    """Restore the built-in synthesis."""
    if _original is None:
        return
    if ohbot_module is None:
        from ohbot import ohbot as ohbot_module  # type: ignore[no-redef]
    ohbot_module._generateSpeechFile = _original
