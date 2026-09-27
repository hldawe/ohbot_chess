# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Speech input: Vosk, with the grammar rebuilt from the legal moves each turn.

WHY VOSK AND NOT AN OPEN-VOCABULARY RECOGNISER

Vosk accepts a GRAMMAR -- an explicit list of what it is allowed to return.
Rebuilt every turn from the moves that are actually legal in the current
position, it becomes structurally impossible for the recogniser to return a
move that cannot be played. "Knight" cannot come back as "night", because
"night" is not in the grammar.

An open-vocabulary model cannot offer that. Fuzzy-matching its transcript
against the legal move set recovers some of it, but only after the fact, and it
fails in exactly the case that matters: a confident transcription of a
plausible wrong move. For a child speaker that difference is the whole game.

The cost is that the grammar has to be rebuilt on every turn, which is cheap,
and that anything outside it comes back as unknown, which is the desired
behaviour rather than a limitation.

THE ECHO PROBLEM

Speech comes out of the laptop and the microphone is usually on the laptop too,
so the robot hears itself far more readily than it did on hardware where both
lived in the robot. Three layers handle it, and all three are needed:

  1. Gate on body.speaking -- discard audio while the robot talks, and reset
     the utterance rather than keeping a partial one.
  2. Drain the input buffer when speech ends, so queued echo doesn't arrive
     late and get treated as the child's reply.
  3. RMS voice activity detection against a calibrated noise floor.
"""

from __future__ import annotations

import json
import queue
import re
import time
from collections.abc import Iterable
from typing import Any

from . import config

# Control words, handled by a deterministic branch BEFORE any move parsing.
# `stop` in particular must never be ambiguous, so it never reaches a parser
# that might decide it looks a bit like a move.
CONTROL_WORDS = {
    "again": "repeat",
    "repeat": "repeat",
    "say that again": "repeat",
    "what": "repeat",
    "board": "board",
    "read the board": "board",
    "where are we": "board",
    # Show it on screen -- distinct from `board`, which reads it aloud for
    # someone who cannot see a screen. Both are wanted.
    "show": "show",
    "show the board": "show",
    "print the board": "show",
    "draw the board": "show",
    # Correct it. Typed only in practice, but harmless in the grammar.
    "fix": "fix",
    "fix the board": "fix",
    "correct the board": "correct",
    "edit the board": "fix",
    "edit": "fix",
    "take that back": "undo",
    "takeback": "undo",
    "undo": "undo",
    # Telling the robot its move cannot be played. Without this there is no
    # way to report a board desync at the moment it actually bites: the robot
    # asks for a move that is legal only in the position it thinks it is in,
    # and the person is left with nothing to say.
    "cant do that": "cannot",
    "can't do that": "cannot",
    "i cant do that": "cannot",
    "i can't do that": "cannot",
    "cannot do that": "cannot",
    "thats not legal": "cannot",
    "that's not legal": "cannot",
    "not legal": "cannot",
    "illegal": "cannot",
    "illegal move": "cannot",
    "impossible": "cannot",
    "thats impossible": "cannot",
    "that piece cant move there": "cannot",
    "try another": "cannot",
    "try something else": "cannot",
    "pick another move": "cannot",
    # With no camera, this is how the robot learns its own move has actually
    # been made on the physical board. It is the only confirmation available,
    # so it is generous about phrasing.
    "done": "done",
    "moved": "done",
    "i moved it": "done",
    "moved it": "done",
    "finished": "done",
    "okay": "done",
    "ok": "done",
    "yes": "done",
    "help": "help",
    "resign": "resign",
    "i resign": "resign",
    "give up": "resign",
    "stop": "stop",
    "stop the game": "stop",
}


class MicrophoneBlocked(RuntimeError):
    """Raised when the OS hands us digital silence instead of audio."""


class VoskUnavailable(RuntimeError):
    """Raised when the Vosk model is missing or unloadable."""


_CONTROL_PUNCT = re.compile(r"[^\w\s\']")


def control_word(text: str) -> str | None:
    """Map an utterance to a control command, or None if it isn't one.

    Punctuation is stripped, because these are typed as often as spoken and
    "that's not legal." with a full stop must not fall through to the move
    parser. Apostrophes are kept, so both "cant" and "can't" are listed.
    """
    cleaned = _CONTROL_PUNCT.sub("", (text or "").lower())
    cleaned = " ".join(cleaned.split())
    return CONTROL_WORDS.get(cleaned)


def build_grammar(phrases: Iterable[str]) -> str:
    """The JSON grammar Vosk expects.

    '[unk]' is included deliberately: without it the recogniser is forced to
    return SOMETHING from the list, and a cough becomes a move. With it,
    unrecognised audio comes back as unknown and the robot asks again -- which
    is the correct behaviour and much safer than a confident wrong move.
    """
    words = sorted({p.strip().lower() for p in phrases if p and p.strip()})
    words.extend(sorted(CONTROL_WORDS))
    return json.dumps(sorted(set(words)) + ["[unk]"])


def missing_words(model: Any, recogniser_class: Any, rate: int, words: Iterable[str]) -> list[str]:
    """Which grammar words the Vosk model has never heard of.

    A closed grammar only works if every word in it exists in the model's
    lexicon. Vosk reports unknown words on stderr from its C layer and then
    carries on, so the failure is silent from Python: the grammar is built,
    recognition runs, and nothing is ever matched.

    Single letters are the live risk here -- a grammar full of "e four" and
    "b five" depends on the model knowing "e" and "b" as words, which is not
    something a general dictation lexicon is guaranteed to include.

    The C library writes to file descriptor 2 directly, so Python-level
    redirection is not enough and the descriptor itself has to be swapped.
    """
    import os
    import tempfile

    unique = sorted({w.strip().lower() for w in words if w and w.strip()})
    if not unique:
        return []

    saved = os.dup(2)
    with tempfile.TemporaryFile(mode="w+") as capture:
        try:
            os.dup2(capture.fileno(), 2)
            recogniser_class(model, rate, json.dumps(unique + ["[unk]"]))
        finally:
            os.dup2(saved, 2)
            os.close(saved)
        capture.seek(0)
        log = capture.read()

    found = []
    for line in log.splitlines():
        lowered = line.lower()
        if "missing" in lowered or "unknown word" in lowered or "not in lexicon" in lowered:
            for word in unique:
                if f"'{word}'" in line or f'"{word}"' in line or f" {word} " in line:
                    found.append(word)
    return sorted(set(found))


def _rms(block: Any) -> float:
    import numpy as np

    return float(np.sqrt(np.mean(np.square(block))))


class Listener:
    """Captures an utterance and recognises it against a per-turn grammar."""

    def __init__(
        self,
        model_dir: str = config.VOSK_MODEL_DIR,
        device: int | None = None,
        sample_rate: int = config.SAMPLE_RATE,
        noise_multiplier: float = config.NOISE_MULTIPLIER,
        silence_seconds: float = config.SILENCE_SECONDS,
        min_speech_seconds: float = config.MIN_SPEECH_SECONDS,
    ) -> None:
        try:
            from vosk import KaldiRecognizer, Model
        except ImportError as e:  # pragma: no cover - depends on install
            raise VoskUnavailable("vosk is not installed. Run: pip install vosk") from e

        try:
            self._model = Model(model_dir)
        except Exception as e:
            raise VoskUnavailable(
                f"Could not load the Vosk model from {model_dir!r}.\n"
                "Download vosk-model-small-en-us-0.15 from alphacephei.com/vosk/models "
                "and unzip it, then pass --vosk-model <dir>."
            ) from e

        self._recogniser_class = KaldiRecognizer
        self.device = device
        self.sample_rate = sample_rate
        self.noise_multiplier = noise_multiplier
        self.silence_seconds = silence_seconds
        self.min_speech_seconds = min_speech_seconds
        self.threshold = config.NOISE_FLOOR

    # -- calibration ---------------------------------------------------

    def calibrate(self) -> None:
        """Measure room noise so the threshold suits the actual room."""
        import numpy as np
        import sounddevice as sd

        levels = []
        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            blocksize=config.BLOCK,
            device=self.device,
            dtype="float32",
        ) as stream:
            deadline = time.time() + config.CALIBRATION_SECONDS
            while time.time() < deadline:
                block, _ = stream.read(config.BLOCK)
                levels.append(_rms(block[:, 0]))

        if levels and max(levels) == 0.0:
            # Digital silence is not a quiet room -- the OS is handing us
            # nothing. Without this check the listener waits forever for a loud
            # block that can never arrive.
            raise MicrophoneBlocked(
                "The microphone returned pure silence.\n"
                "The operating system has probably not granted microphone "
                "access to this terminal, or the input device is muted.\n"
                "On macOS: System Settings > Privacy & Security > Microphone."
            )

        baseline = float(np.median(levels)) if levels else 0.0
        self.threshold = max(baseline * self.noise_multiplier, config.NOISE_FLOOR)

    # -- capture -------------------------------------------------------

    def listen(
        self,
        grammar: str,
        body: Any = None,
        timeout: float = config.LISTEN_TIMEOUT_SECONDS,
    ) -> str:
        """Wait for one utterance and return its transcript.

        Returns '' if nothing intelligible arrived before the timeout, which
        the caller must treat as "ask again", never as a move.

        CAPTURE IS CALLBACK-DRIVEN, NOT A READ LOOP.

        Reading blocks synchronously and then handing each one to Vosk means
        the microphone keeps filling its buffer while recognition runs, and
        PortAudio reports the resulting overflow. Skipping an overflowed block
        -- which is the obvious thing to do -- throws away the audio, and since
        overflow happens on nearly every iteration once recognition is in the
        loop, it throws away almost all of it. The symptom is a recogniser that
        appears simply not to work.

        A callback pushing into a queue decouples capture from recognition, so
        nothing is dropped however long a block takes to process.

        RESULTS MUST BE COLLECTED WHEN THEY ARE READY.

        AcceptWaveform returns True when Vosk has finalised an utterance, and
        the recogniser RESETS at that point. Ignoring the return value and
        calling FinalResult() at the end therefore returns whatever trailing
        fragment came after the reset, which is usually nothing at all.
        """
        import numpy as np
        import sounddevice as sd

        recogniser = self._recogniser_class(self._model, self.sample_rate, grammar)
        recogniser.SetWords(False)

        audio: queue.Queue[bytes] = queue.Queue()

        def callback(indata: Any, _frames: int, _time: Any, _status: Any) -> None:
            audio.put(bytes(indata))

        block_seconds = config.BLOCK / float(self.sample_rate)
        silence_limit = max(1, int(self.silence_seconds / block_seconds))
        started = False
        speech_blocks = 0
        silence_blocks = 0
        deadline = time.time() + timeout

        with sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=config.BLOCK,
            device=self.device,
            dtype="int16",
            channels=1,
            callback=callback,
        ):
            while time.time() < deadline:
                try:
                    data = audio.get(timeout=0.5)
                except queue.Empty:
                    continue

                # Never listen while the robot is talking, or it transcribes
                # its own voice and holds a conversation with itself.
                if body is not None and body.speaking.is_set():
                    _empty(audio)
                    recogniser = self._recogniser_class(self._model, self.sample_rate, grammar)
                    started, speech_blocks, silence_blocks = False, 0, 0
                    continue

                samples = np.frombuffer(data, dtype="<i2")
                level = float(np.sqrt(np.mean(np.square(samples / 32768.0))))
                loud = level > self.threshold

                if recogniser.AcceptWaveform(data):
                    text = _text_of(recogniser.Result())
                    if text:
                        return text
                    # A finalised but empty result is just silence passing.
                    started, speech_blocks, silence_blocks = False, 0, 0
                    continue

                if not started:
                    if loud:
                        started = True
                        speech_blocks = 1
                    continue

                if loud:
                    speech_blocks += 1
                    silence_blocks = 0
                else:
                    silence_blocks += 1

                if silence_blocks >= silence_limit:
                    break

        if not started:
            return ""
        if speech_blocks * block_seconds < self.min_speech_seconds:
            return ""  # a cough or a door, not speech

        return _text_of(recogniser.FinalResult())


def _text_of(payload: str) -> str:
    """Pull the transcript out of a Vosk result, treating unknown as nothing."""
    try:
        text = str(json.loads(payload).get("text", "")).strip()
    except (ValueError, AttributeError):
        return ""
    return "" if text in ("", "[unk]") else text


def _empty(audio: queue.Queue[bytes]) -> None:
    """Throw away everything queued.

    Called when the robot is speaking. Without it, the echo of its own voice is
    still sitting in the queue and arrives as the person's reply.
    """
    while True:
        try:
            audio.get_nowait()
        except queue.Empty:
            return
