# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The expression vocabulary, including the two hardware unknowns."""

from __future__ import annotations

import pytest

from ohbot_chess import expression as ex


def test_module_needs_no_robot_library() -> None:
    """expression.py must import nothing from the robot library.

    Motor numbers are fixed hardware facts. Reading them from the library
    instead would mean the vocabulary could not be imported, inspected or
    tested without a serial port -- which is exactly the coupling this layer
    exists to avoid.
    """
    import inspect

    source = inspect.getsource(ex)
    assert "import ohbot" not in source
    assert "from ohbot" not in source


# -- poses ------------------------------------------------------------------


def test_every_pose_is_wellformed() -> None:
    for name, pose in ex.POSES.items():
        assert pose, f"{name} is empty"
        for motor, position in pose.items():
            assert 0 <= motor <= 7, f"{name} uses motor {motor}"
            assert 0 <= position <= 10, f"{name} sets {motor} to {position}"


def test_lids_rest_open() -> None:
    """Resting the lids at 5 leaves the robot permanently half asleep."""
    assert ex.REST[ex.LIDBLINK] == 10
    assert ex.POSES["neutral"][ex.LIDBLINK] == 10


def test_unknown_pose_raises_with_the_options() -> None:
    with pytest.raises(KeyError) as excinfo:
        ex.pose("smug")
    assert "sympathetic" in str(excinfo.value)


# -- the head-roll unknown --------------------------------------------------


def test_headroll_is_dropped_when_absent() -> None:
    for name in ex.POSES:
        assert ex.HEADROLL not in ex.pose(name, has_headroll=False)


def test_sympathetic_is_rebuilt_not_merely_stripped() -> None:
    """The head-cock is what makes sympathy land.

    Stripping the motor and leaving the rest gives a blank stare. The
    substitute has to compensate -- lids lower, head drops further -- or the
    most important pose in a coaching app silently stops working on hardware
    where one servo is missing.
    """
    with_roll = ex.pose("sympathetic", has_headroll=True)
    without = ex.pose("sympathetic", has_headroll=False)

    assert ex.HEADROLL in with_roll
    assert ex.HEADROLL not in without
    # Compensated, not just missing a key.
    assert without[ex.LIDBLINK] < with_roll[ex.LIDBLINK]
    assert without[ex.HEADNOD] < with_roll[ex.HEADNOD]


def test_roll_only_gesture_degrades_to_something_visible() -> None:
    """A gesture that silently does nothing looks like a crash."""
    frames = ex.gesture("tilt", has_headroll=False)
    assert frames, "tilt vanished entirely without head roll"
    assert all(frame[0] != ex.HEADROLL for frame in frames)


def test_other_gestures_just_lose_their_roll_frames() -> None:
    frames = ex.gesture("perk_up", has_headroll=False)
    assert frames
    assert all(frame[0] != ex.HEADROLL for frame in frames)
    assert any(frame[0] == ex.HEADNOD for frame in frames)


# -- restraint --------------------------------------------------------------


def test_no_startle_gestures_in_the_vocabulary() -> None:
    """This is a chess coach, not a chat robot.

    Nothing at a chessboard warrants a flinch, and having one available only
    invites it being used.
    """
    for banned in ("shiver", "recoil", "double_take"):
        assert banned not in ex.GESTURES


# -- gaze -------------------------------------------------------------------


def test_uncalibrated_gaze_falls_back_to_the_board() -> None:
    """Uncalibrated is a shipping state, not a failure.

    A MIScalibrated gaze -- confidently looking at the wrong square -- is far
    worse than looking at the board in general, so this stays off until the
    calibration exists.
    """
    gaze = ex.BoardGaze()
    assert not gaze.calibrated
    assert gaze.square("e4") == ex.LOOK_DIRECTIONS["board"]
    assert gaze.square("a1") == gaze.square("h8")


def test_calibrated_gaze_maps_corners_and_interpolates() -> None:
    gaze = ex.BoardGaze(a1=(8.0, 1.0), h8=(2.0, 4.0))
    assert gaze.calibrated
    assert gaze.square("a1") == (8.0, 1.0)
    assert gaze.square("h8") == (2.0, 4.0)

    middle = gaze.square("d4")
    assert 2.0 < middle[0] < 8.0
    assert 1.0 < middle[1] < 4.0


def test_gaze_stays_within_motor_range() -> None:
    gaze = ex.BoardGaze(a1=(0.0, 0.0), h8=(10.0, 10.0))
    for square in ("a1", "h8", "d4", "e5"):
        x, y = gaze.square(square)
        assert 0 <= x <= 10 and 0 <= y <= 10


def test_gaze_round_trips_through_a_dict() -> None:
    original = ex.BoardGaze(a1=(8.0, 1.0), h8=(2.0, 4.0))
    restored = ex.BoardGaze.from_dict(original.to_dict())
    assert restored.square("e4") == original.square("e4")


def test_malformed_calibration_is_ignored_not_fatal() -> None:
    assert not ex.BoardGaze.from_dict({"a1": [1.0], "h8": []}).calibrated
    assert not ex.BoardGaze.from_dict(None).calibrated


def test_head_follows_eyes_only_partway() -> None:
    """Driving the head the full distance looks like a security camera."""
    eyes, head = ex.look_targets(x=9, y=5)
    assert eyes[ex.EYETURN] == 9
    assert 5 < head[ex.HEADTURN] < 9


def test_head_targets_omit_roll_when_absent() -> None:
    _, head = ex.look_targets(x=9, y=5, has_headroll=False)
    assert ex.HEADROLL not in head
