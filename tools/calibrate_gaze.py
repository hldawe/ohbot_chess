#!/usr/bin/env python3
# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Teach the robot where the board is, so it can look at the square it names.

    python tools/calibrate_gaze.py

Two corners is enough for a linear map, and about as much fiddling as anyone
will tolerate before a game.

You drive the eyes to a corner with the keyboard and press enter. Repeat for
the opposite corner. That's it.

THIS IS OPTIONAL. Without it the robot looks down at the board in general,
which is what the previous hardware always did. A MISCALIBRATED gaze is much
worse than none -- confidently looking at the wrong square undermines
everything else the robot does -- so if the result looks off, delete the file
rather than living with it.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ohbot_chess import config  # noqa: E402
from ohbot_chess import expression as ex

STEP = 0.5
KEYS = """
  w / s   eyes up / down
  a / d   eyes left / right
  enter   accept this corner
  q       give up without saving
"""


def drive(ohbot, corner: str) -> tuple[float, float] | None:
    x, y = 5.0, 3.0
    print(f"\nAim the eyes at the {corner} corner of the board.")
    print(KEYS)

    while True:
        ohbot.move(ex.EYETURN, x, 8)
        ohbot.move(ex.EYETILT, y, 8)
        # A little head follow, so you are aiming the face rather than
        # just the eyeballs -- that is what the game will actually do.
        ohbot.move(ex.HEADTURN, 5 + (x - 5) * ex.HEAD_FOLLOW, 3)
        ohbot.move(ex.HEADNOD, 5 + (y - 5) * ex.HEAD_FOLLOW, 3)

        try:
            key = input(f"  [{x:.1f}, {y:.1f}] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if key == "q":
            return None
        if key == "":
            return (x, y)
        for char in key:
            if char == "w":
                y = min(10.0, y + STEP)
            elif char == "s":
                y = max(0.0, y - STEP)
            elif char == "a":
                x = min(10.0, x + STEP)
            elif char == "d":
                x = max(0.0, x - STEP)


def main() -> int:
    try:
        from ohbot import ohbot
    except ImportError:
        print("The ohbot library is not installed. Run: pip install ohbot")
        return 2

    from ohbot_chess import serial_safe

    serial_safe.install(ohbot)
    ohbot.reset()

    print("Board gaze calibration")
    print("Put the board where it will be during the game, then set it up.")

    try:
        a1 = drive(ohbot, "a1 (nearest you on your left, if you play white)")
        if a1 is None:
            print("Cancelled. Nothing written.")
            return 1

        h8 = drive(ohbot, "h8 (the opposite corner, far side)")
        if h8 is None:
            print("Cancelled. Nothing written.")
            return 1
    finally:
        ohbot.reset()
        ohbot.close()

    gaze = ex.BoardGaze(a1=a1, h8=h8)
    with open(config.GAZE_CALIBRATION_FILE, "w") as handle:
        json.dump(gaze.to_dict(), handle, indent=2)

    print(f"\nWritten to {config.GAZE_CALIBRATION_FILE}.")
    print("\nSanity check -- where it thinks these squares are:")
    for square in ("a1", "h8", "d4", "e5", "a8", "h1"):
        x, y = gaze.square(square)
        print(f"  {square}: gaze ({x:.1f}, {y:.1f})")

    print("\nIf those look wrong, delete the file. Looking at the board in")
    print("general is much better than looking confidently at the wrong square.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
