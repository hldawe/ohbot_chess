# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures, and the fakes that make this suite runnable anywhere.

WHY THE FAKES ARE INSTALLED BEFORE ANY IMPORT

The real `ohbot` package calls init() unconditionally at import time: it
enumerates serial ports, writes an ohbotData/ folder, and plays a warm-up
sound. `sounddevice` is worse -- importing it requires PortAudio to be present
on the system, which CI runners do not have.

So both are replaced in sys.modules here, before ohbot_chess is imported. The
suite is then hermetic and identical on Ubuntu, macOS and Windows with no
robot, no audio device and no apt packages.

THE FAKE RECORDS, IT DOES NOT MERELY SILENCE

FakeOhbot keeps every motor command it was given. That recording is the
assertion surface for the behaviours that actually break on this hardware:

  * the mouth being driven while lip sync owns it
  * the head failing to recentre after an utterance, which compounds
  * head-roll keyframes running on a robot with no head-roll servo
  * gestures failing to overlap speech, which is the whole point of the lock

None of those can be caught by asserting that a mock was called.
"""

from __future__ import annotations

import shutil
import sys
import types
from typing import Any

import pytest

# --------------------------------------------------------------------------
# Fake ohbot
# --------------------------------------------------------------------------


class FakeOhbot(types.ModuleType):
    """Stand-in for the ohbot library that records what it was told to do."""

    HEADNOD = 0
    HEADTURN = 1
    EYETURN = 2
    LIDBLINK = 3
    TOPLIP = 4
    BOTTOMLIP = 5
    EYETILT = 6
    HEADROLL = 7

    def __init__(self, name: str = "ohbot") -> None:
        super().__init__(name)
        self.connected = True
        self.speechAudioFile = "ohbotData/ohbotspeech.wav"
        self.motorPos = [5.0] * 8
        # A fitted servo has a type; an absent one does not. This is the table
        # body.detect_headroll reads.
        self.motorType: list[str | None] = ["servo"] * 8
        self.say_duration = 0.0
        self.reset_recording()

    def reset_recording(self) -> None:
        self.moves: list[tuple[int, float, float]] = []
        self.said: list[str] = []
        self.eye_colours: list[tuple[int, int, int]] = []
        self.writes: list[str] = []
        self.closed = False
        self.reset_calls = 0
        # Recorded so a test can assert that a gesture ran DURING speech
        # rather than before or after it.
        self.moves_during_speech: list[tuple[int, float, float]] = []
        self._speaking = False

    # -- the API body.py uses ------------------------------------------

    def move(self, motor: int, pos: float, spd: float = 5, eye: int = 0) -> None:
        self.moves.append((motor, pos, spd))
        if self._speaking:
            self.moves_during_speech.append((motor, pos, spd))
        self.motorPos[motor] = pos

    def say(
        self,
        text: str,
        untilDone: bool = True,
        lipSync: bool = True,
        hdmiAudio: bool = False,
        soundDelay: float = 0.0,
    ) -> None:
        self._speaking = True
        try:
            self.said.append(text)
            if self.say_duration:
                import time

                time.sleep(self.say_duration)
        finally:
            self._speaking = False

    def reset(self) -> None:
        self.reset_calls += 1

    def close(self) -> None:
        self.closed = True

    def setEyeColour(self, r: int, g: int, b: int, sway: int = 0) -> None:
        self.eye_colours.append((r, g, b))

    def readSensor(self, index: int) -> float:
        return 0.0

    def _serwrite(self, s: str) -> None:
        self.writes.append(s)

    def _generateSpeechFile(self, text: str) -> None:
        pass

    def _playSpeech(self, addSilence: bool = False) -> None:
        pass


class FakeSoundDevice(types.ModuleType):
    """Enough of sounddevice to import. Nothing here is ever exercised."""

    def __init__(self, name: str = "sounddevice") -> None:
        super().__init__(name)
        self.default = types.SimpleNamespace(device=(0, 0))

    def query_devices(self, *args: Any, **kwargs: Any) -> Any:
        return []

    class PortAudioError(Exception):
        pass

    def InputStream(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("no audio device in tests")

    def play(self, *args: Any, **kwargs: Any) -> None:
        pass

    def wait(self) -> None:
        pass


_fake_ohbot = FakeOhbot()
sys.modules.setdefault("ohbot", types.ModuleType("ohbot"))
sys.modules["ohbot"].ohbot = _fake_ohbot  # type: ignore[attr-defined]
sys.modules["ohbot.ohbot"] = _fake_ohbot
sys.modules.setdefault("sounddevice", FakeSoundDevice())


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def fake_ohbot() -> Any:
    """The shared fake, with its recording cleared."""
    _fake_ohbot.reset_recording()
    _fake_ohbot.motorType = ["servo"] * 8
    _fake_ohbot.say_duration = 0.0
    return _fake_ohbot


@pytest.fixture
def stockfish_path() -> str:
    """Path to a real Stockfish, or skip.

    Engine and coach behaviour is tested against the real binary rather than a
    stub. A stubbed engine can only confirm that the code calls it -- it cannot
    catch a sign error in centipawn loss, which is the bug this code is most
    likely to have.
    """
    found = shutil.which("stockfish")
    if not found:
        pytest.skip("stockfish not installed")
    return found


@pytest.fixture
def mock_body() -> Any:
    from ohbot_chess.body import MockBody

    return MockBody(verbose=False)
