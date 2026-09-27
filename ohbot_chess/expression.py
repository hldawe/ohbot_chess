# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The expression vocabulary: poses, gestures and gaze.

This module imports NOTHING from the robot library. Motor numbers are fixed
hardware facts and are written here as literals, so the vocabulary can be
imported, read and tested with no library, no serial port and no fake. Only
body.py talks to the hardware.

A pose is a held face. A gesture is a timed keyframe sequence. Gaze aims the
eyes, optionally with the head following.

TWO RULES

1. MOUTH OWNERSHIP. While speaking, the lip-sync thread owns TOPLIP and
   BOTTOMLIP. Poses may set them, but those values are dropped while speech is
   in progress or the smile fights the lip sync and produces mush.

2. RESTRAINT. This is a chess coach, not a chat robot. At most one gesture per
   turn, and none on a routine move announcement. A robot that gestures on
   every sentence looks twitchy, and the movements that should mean something
   stop meaning anything.
"""

from __future__ import annotations

from collections.abc import Iterable

# -- motors -----------------------------------------------------------------
# Fixed by the hardware. TOPLIP (4) and HEADROLL (7) are real despite being
# absent from the vendor's documentation table.

HEADNOD = 0  # pitch: low = looking down
HEADTURN = 1  # yaw: low = its right, high = its left
EYETURN = 2  # eye yaw
LIDBLINK = 3  # 10 = wide open, 0 = shut. Rest is 10.
TOPLIP = 4  # owned by lip sync while speaking
BOTTOMLIP = 5  # owned by lip sync while speaking
EYETILT = 6  # eye pitch: low = looking down
HEADROLL = 7  # tilt: the head-cock. Not fitted on every robot.

MOUTH = (TOPLIP, BOTTOMLIP)

# Axes that aim the face at the person. A pose may leave these off-centre for
# character, but they must be returned or the offset compounds utterance after
# utterance until the robot is addressing the wall.
ORIENTATION = (HEADTURN, HEADROLL, EYETURN)

REST = {
    HEADNOD: 5,
    HEADTURN: 5,
    EYETURN: 5,
    LIDBLINK: 10,  # resting at 5 leaves it permanently half-asleep
    EYETILT: 5,
    HEADROLL: 5,
}

# -- poses ------------------------------------------------------------------
#
# Narrower than a general-purpose set on purpose. There is no `startled`, no
# `shiver`, no `recoil`: nothing at a chessboard warrants them, and having them
# available only invites misuse.

POSES: dict[str, dict[int, float]] = {
    "neutral": {LIDBLINK: 10, HEADNOD: 5, EYETILT: 5, HEADROLL: 5},
    # Looking up and away -- the universal "I'm working on it".
    "thinking": {LIDBLINK: 7, HEADNOD: 6, EYETILT: 8, EYETURN: 7, HEADROLL: 6},
    # Warm but not manic. This is the everyday good-news face.
    "pleased": {LIDBLINK: 9, HEADNOD: 6, EYETILT: 6, HEADROLL: 5, BOTTOMLIP: 7, TOPLIP: 6},
    # Softened, lowered, head tilted towards you. The head-cock is what makes
    # this land; see SYMPATHETIC_NO_ROLL for the fallback.
    "sympathetic": {LIDBLINK: 6, HEADNOD: 4, EYETILT: 4, HEADROLL: 7, BOTTOMLIP: 5, TOPLIP: 5},
    # Genuine admiration -- wider than pleased, head up.
    "impressed": {LIDBLINK: 10, HEADNOD: 7, EYETILT: 7, HEADROLL: 5, BOTTOMLIP: 8, TOPLIP: 7},
    # Not alarmed. A slight narrowing, head level: "are you sure about that?"
    "concerned": {LIDBLINK: 7, HEADNOD: 5, EYETILT: 5, HEADROLL: 6, BOTTOMLIP: 4, TOPLIP: 4},
    # Light, a bit mischievous. For teasing and for its own good moves.
    "playful": {LIDBLINK: 9, HEADNOD: 6, EYETILT: 7, HEADROLL: 4, BOTTOMLIP: 7, TOPLIP: 5},
}

# Reconstruction of `sympathetic` for a robot with no head-roll servo.
#
# The head-cock is the single most effective thing this face can do and it is
# the one motor that may be absent. Dropping it silently turns sympathy into a
# blank stare, so it is rebuilt from what remains: lids lower, head drops a
# little further, and the gaze settles just below the child's eyeline. That
# reads as attentive-and-serious rather than warm -- a downgrade, but a
# deliberate and legible one.
SYMPATHETIC_NO_ROLL = {
    LIDBLINK: 5,
    HEADNOD: 3,
    EYETILT: 3,
    BOTTOMLIP: 5,
    TOPLIP: 5,
}

# Poses that need rewriting when HEADROLL is absent.
NO_ROLL_SUBSTITUTES = {"sympathetic": SYMPATHETIC_NO_ROLL}


def pose(name: str, has_headroll: bool = True) -> dict[int, float]:
    """Motor targets for a pose, substituting where head-roll is unavailable."""
    if name not in POSES:
        raise KeyError("Unknown pose {!r}. Available: {}".format(name, ", ".join(sorted(POSES))))
    if not has_headroll and name in NO_ROLL_SUBSTITUTES:
        return dict(NO_ROLL_SUBSTITUTES[name])
    target = dict(POSES[name])
    if not has_headroll:
        target.pop(HEADROLL, None)
    return target


# -- gestures ---------------------------------------------------------------
# Keyframes: (motor, position, speed, hold_seconds). Speed is 0-10, 10 fastest.
# hold_seconds is how long to wait before the next keyframe.
#
# Gestures run on a thread so they play UNDERNEATH speech. That simultaneity is
# what separates an expressive robot from a talking statue.

GESTURES: dict[str, list[tuple[int, float, float, float]]] = {
    "nod": [
        (HEADNOD, 3, 8, 0.22),
        (HEADNOD, 6, 8, 0.22),
        (HEADNOD, 3, 8, 0.22),
        (HEADNOD, 5, 6, 0.20),
    ],
    # Slow and shallow. A brisk nod reads as agreement; a slow one as sympathy.
    "slow_nod": [
        (HEADNOD, 4, 2, 0.60),
        (HEADNOD, 5, 2, 0.60),
        (HEADNOD, 4, 2, 0.60),
        (HEADNOD, 5, 2, 0.40),
    ],
    "tilt": [
        (HEADROLL, 8, 3, 0.60),
        (HEADROLL, 5, 3, 0.30),
    ],
    "lean_in": [
        (HEADNOD, 7, 3, 0.50),
        (LIDBLINK, 10, 6, 0.40),
    ],
    "perk_up": [
        (LIDBLINK, 10, 10, 0.10),
        (HEADNOD, 7, 8, 0.25),
        (HEADROLL, 6, 6, 0.25),
        (HEADNOD, 5, 5, 0.15),
        (HEADROLL, 5, 6, 0.15),  # return the roll or it leaks into the next line
    ],
    "look_away": [
        (EYETURN, 8, 5, 0.35),
        (HEADTURN, 6, 3, 0.50),
        (EYETURN, 5, 4, 0.30),
        (HEADTURN, 5, 3, 0.30),
    ],
    "blink": [
        (LIDBLINK, 0, 10, 0.10),
        (LIDBLINK, 10, 10, 0.05),
    ],
    "double_blink": [
        (LIDBLINK, 0, 10, 0.09),
        (LIDBLINK, 10, 10, 0.09),
        (LIDBLINK, 0, 10, 0.09),
        (LIDBLINK, 10, 10, 0.05),
    ],
}

# Gestures that are entirely head-roll and therefore vanish without that servo.
# `tilt` degrades to a small nod rather than to nothing, because a gesture that
# silently does not happen looks like a crash.
ROLL_ONLY = {"tilt"}
TILT_NO_ROLL = [
    (HEADNOD, 6, 3, 0.45),
    (HEADNOD, 5, 3, 0.30),
]


def gesture(name: str, has_headroll: bool = True) -> list[tuple[int, float, float, float]]:
    """Keyframes for a gesture, with head-roll frames handled if absent."""
    if name not in GESTURES:
        raise KeyError(
            "Unknown gesture {!r}. Available: {}".format(name, ", ".join(sorted(GESTURES)))
        )
    frames = GESTURES[name]
    if has_headroll:
        return list(frames)
    if name in ROLL_ONLY:
        return list(TILT_NO_ROLL)
    return [f for f in frames if f[0] != HEADROLL]


GESTURE_NAMES = sorted(GESTURES)
POSE_NAMES = sorted(POSES)


# -- gaze -------------------------------------------------------------------

# Named targets as (x, y): x is 0 right .. 10 left, y is 0 down .. 10 up.
LOOK_DIRECTIONS = {
    "child": (5, 6),  # slightly up: the child's face is above the board
    "ahead": (5, 5),
    "board": (5, 2),  # down, towards the table
    "away": (8, 7),  # up and to one side, for thinking
    "left": (9, 5),
    "right": (1, 5),
}

# How far the head follows the eyes. People saccade first and the head catches
# up partway; driving the head the full distance looks like a security camera
# tracking a fly rather than a glance.
HEAD_FOLLOW = 0.55


def gaze_positions(x: float = 5, y: float = 5) -> dict[int, float]:
    return {EYETURN: x, EYETILT: y}


def look_targets(
    x: float = 5,
    y: float = 5,
    with_head: bool = True,
    head_follow: float = HEAD_FOLLOW,
    has_headroll: bool = True,
) -> tuple[dict[int, float], dict[int, float]]:
    """Eye and head targets for looking somewhere.

    Returned separately so the caller can move the eyes first and the head a
    moment later. That lag is what makes it read as a glance.
    """
    eyes = {EYETURN: x, EYETILT: y}
    if not with_head:
        return eyes, {}

    def follow(value: float) -> float:
        return 5 + (value - 5) * head_follow

    head = {HEADTURN: follow(x), HEADNOD: follow(y)}
    if has_headroll:
        # Real heads tip a little when turning to look; without it the turn
        # feels stiff.
        head[HEADROLL] = 5 + (x - 5) * 0.2
    return eyes, head


# -- board gaze -------------------------------------------------------------

FILES = "abcdefgh"


class BoardGaze:
    """Maps chess squares onto gaze coordinates.

    Calibrated from two opposite corners, which is enough for a linear map and
    is about as much fiddling as anyone will tolerate before a game.

    Uncalibrated, every square resolves to the same fixed "board" direction.
    That is a legitimate shipping state, not a degraded one: the robot looks
    down at the board rather than at a specific square, which is what it did on
    the previous hardware. A MIScalibrated gaze is far worse than none --
    confidently looking at the wrong square undermines everything else -- so
    this stays off until the calibration file exists.
    """

    def __init__(
        self,
        a1: tuple[float, float] | None = None,
        h8: tuple[float, float] | None = None,
    ) -> None:
        self.a1 = a1
        self.h8 = h8

    @property
    def calibrated(self) -> bool:
        return self.a1 is not None and self.h8 is not None

    def square(self, name: str) -> tuple[float, float]:
        """Gaze (x, y) for a square name like 'e4'."""
        if not self.calibrated or len(name) != 2 or name[0] not in FILES:
            return LOOK_DIRECTIONS["board"]

        assert self.a1 is not None and self.h8 is not None
        file_index = FILES.index(name[0])
        rank_index = int(name[1]) - 1

        fx = file_index / 7.0
        fy = rank_index / 7.0
        x = self.a1[0] + (self.h8[0] - self.a1[0]) * fx
        y = self.a1[1] + (self.h8[1] - self.a1[1]) * fy
        return (_clamp(x), _clamp(y))

    def to_dict(self) -> dict[str, list[float]]:
        return {
            "a1": list(self.a1 or ()),
            "h8": list(self.h8 or ()),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Iterable[float]] | None) -> BoardGaze:
        if not data:
            return cls()
        a1 = list(data.get("a1") or [])
        h8 = list(data.get("h8") or [])
        if len(a1) != 2 or len(h8) != 2:
            return cls()
        return cls((a1[0], a1[1]), (h8[0], h8[1]))


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, value))
