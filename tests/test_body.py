# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The body layer, asserted against what the fake was actually told to do.

These are the behaviours that have genuinely broken on this hardware, so they
are asserted on recorded motor commands rather than on mock call counts.
"""

from __future__ import annotations

import time
from typing import Any

from ohbot_chess import expression as ex
from ohbot_chess import serial_safe
from ohbot_chess.body import MockBody, OhbotBody, detect_headroll


def build(fake: Any, **kwargs: Any) -> OhbotBody:
    kwargs.setdefault("idle", False)
    body = OhbotBody(**kwargs)
    body._ohbot = fake
    return body


# -- mouth ownership --------------------------------------------------------


def test_mouth_is_not_driven_while_speaking(fake_ohbot: Any) -> None:
    """Lip sync owns the mouth during speech.

    A pose that also sets the mouth fights the lip-sync thread and produces
    mush. Poses may still carry mouth values -- they apply when quiet.
    """
    body = build(fake_ohbot)
    body.speaking.set()
    body.express("pleased")  # sets BOTTOMLIP and TOPLIP
    body.speaking.clear()

    driven = {motor for motor, _, _ in fake_ohbot.moves}
    assert ex.TOPLIP not in driven
    assert ex.BOTTOMLIP not in driven


def test_mouth_is_driven_when_quiet(fake_ohbot: Any) -> None:
    body = build(fake_ohbot)
    body.express("pleased")
    driven = {motor for motor, _, _ in fake_ohbot.moves}
    assert ex.BOTTOMLIP in driven


# -- recentring -------------------------------------------------------------


def test_speaking_recentres_the_aiming_axes(fake_ohbot: Any) -> None:
    """Without this the tilt compounds until the robot addresses the wall.

    Poses tilt the head for character. Nothing put it back, so the offset
    persisted into the next utterance and accumulated.
    """
    body = build(fake_ohbot)
    body.speak("Your move.", pose="sympathetic")

    final = {}
    for motor, position, _ in fake_ohbot.moves:
        final[motor] = position
    for motor in ex.ORIENTATION:
        assert final.get(motor) == 5, f"motor {motor} left at {final.get(motor)}"


def test_emotional_face_survives_recentring(fake_ohbot: Any) -> None:
    """Only the aiming axes reset. Lids and pitch carry the expression."""
    body = build(fake_ohbot)
    body.recentre()
    driven = {motor for motor, _, _ in fake_ohbot.moves}
    assert ex.LIDBLINK not in driven
    assert ex.HEADNOD not in driven


# -- head roll --------------------------------------------------------------


def test_headroll_commands_are_suppressed_when_absent(fake_ohbot: Any) -> None:
    body = build(fake_ohbot, has_headroll=False)
    body.express("sympathetic")
    body.perform("tilt", blocking=True)

    driven = {motor for motor, _, _ in fake_ohbot.moves}
    assert ex.HEADROLL not in driven
    assert driven, "everything was suppressed, not just head roll"


def test_headroll_detection_reads_the_motor_table(fake_ohbot: Any) -> None:
    fake_ohbot.motorType = ["servo"] * 8
    assert detect_headroll(fake_ohbot) is True

    fake_ohbot.motorType = ["servo"] * 7 + [None]
    assert detect_headroll(fake_ohbot) is False


def test_headroll_detection_defaults_to_present_on_doubt() -> None:
    """A fitted servo left unused loses the head-cock.

    An unfitted one that gets driven only produces an ignored command. So
    uncertainty resolves towards present.
    """

    class Odd:
        pass

    assert detect_headroll(Odd()) is True


def test_explicit_override_beats_detection(fake_ohbot: Any) -> None:
    fake_ohbot.motorType = ["servo"] * 7 + [None]
    body = build(fake_ohbot, has_headroll=True)
    assert body.has_headroll is True


# -- eye colour -------------------------------------------------------------


def test_eye_colour_is_a_noop_without_the_accessory(fake_ohbot: Any) -> None:
    """setEyeColour has no readback, so a missing accessory is undetectable.

    That is fine as long as colour is never the sole signal of a state -- see
    test_presentation.
    """
    body = build(fake_ohbot, has_eyes=False)
    body.set_state("thinking")
    assert fake_ohbot.eye_colours == []


def test_eye_colour_is_used_when_fitted(fake_ohbot: Any) -> None:
    body = build(fake_ohbot, has_eyes=True)
    body.set_state("thinking")
    assert fake_ohbot.eye_colours


# -- gestures ---------------------------------------------------------------


def test_gesture_runs_underneath_speech(fake_ohbot: Any) -> None:
    """Simultaneity is the whole point of the write lock.

    A robot that freezes while talking reads as a speaker with a face. The fake
    records which moves arrived while say() was in progress.
    """
    # A real utterance runs for seconds. Anything shorter than the gesture's
    # first hold would only prove that the keyframe launched, not that it
    # continued to play while audio was in progress.
    fake_ohbot.say_duration = 1.0
    body = build(fake_ohbot)
    body.speak("Thinking about that one.", gesture="nod")

    assert fake_ohbot.moves_during_speech, "no motor moved during speech"
    assert len(fake_ohbot.moves_during_speech) >= 2, "the gesture did not continue"


def test_second_gesture_is_dropped_not_queued(fake_ohbot: Any) -> None:
    """Joining the running gesture would block the CALLER, delaying speech.

    Dropping keeps the robot responsive; queueing makes a burst of coaching
    stutter behind gestures that no longer match what is being said.
    """
    body = build(fake_ohbot)
    body.perform("slow_nod")  # ~2.2s of keyframes
    before = len(fake_ohbot.moves)
    body.perform("nod")
    time.sleep(0.05)
    # The second call returned immediately without starting a second thread.
    assert len(fake_ohbot.moves) - before <= 1


def test_gaze_to_square_is_safe_uncalibrated(fake_ohbot: Any) -> None:
    body = build(fake_ohbot)
    body.look_at_square("e4")
    time.sleep(0.3)
    assert fake_ohbot.moves


# -- lifecycle --------------------------------------------------------------


def test_context_manager_installs_lock_and_releases_motors(fake_ohbot: Any) -> None:
    serial_safe.uninstall(fake_ohbot)
    body = OhbotBody(idle=False)
    body._ohbot = fake_ohbot

    with body:
        assert serial_safe.is_installed()
    assert fake_ohbot.closed, "motors were left drawing current"
    serial_safe.uninstall(fake_ohbot)


# -- mock -------------------------------------------------------------------


def test_mock_body_records_and_validates(mock_body: MockBody) -> None:
    mock_body.speak("Hello.", pose="pleased", gesture="nod")
    assert mock_body.said == ["Hello."]
    assert mock_body.poses == ["pleased"]
    assert mock_body.gestures == ["nod"]


def test_mock_body_rejects_unknown_names(mock_body: MockBody) -> None:
    """The mock validates rather than silently accepting anything.

    A typo that only surfaces on hardware defeats the point of having a mock.
    """
    import pytest

    with pytest.raises(KeyError):
        mock_body.express("smug")
    with pytest.raises(KeyError):
        mock_body.perform("backflip")
