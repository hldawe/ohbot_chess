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
"""Hardware check. Run this before your first game.

    python tools/bringup.py

It answers the two questions the software cannot settle on its own:

  * Is the head-roll servo fitted? Detection reads the library's motor table,
    but the table can be wrong, so this moves the servo and asks you.
  * Are the Illuminating Eyes fitted? This CANNOT be detected at all --
    setEyeColour writes to the serial port with no readback, so a missing
    accessory is indistinguishable from a fitted one. Only your eyes can say.

It prints the flags to pass, so the answers survive into the game.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ohbot_chess import config  # noqa: E402
from ohbot_chess import expression as ex

MOTOR_NAMES = {
    ex.HEADNOD: "head nod (pitch)",
    ex.HEADTURN: "head turn (yaw)",
    ex.EYETURN: "eye turn",
    ex.LIDBLINK: "eyelids",
    ex.TOPLIP: "top lip",
    ex.BOTTOMLIP: "bottom lip",
    ex.EYETILT: "eye tilt",
    ex.HEADROLL: "head roll (the head-cock)",
}


def ask(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower().startswith("y")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def sweep(ohbot, motor: int, label: str) -> None:
    print(f"  moving {label}...", flush=True)
    for position in (3, 7, 5):
        ohbot.move(motor, position, 4)
        time.sleep(0.6)


def main() -> int:
    try:
        from ohbot import ohbot
    except ImportError:
        print("The ohbot library is not installed. Run: pip install ohbot")
        return 2

    from ohbot_chess import serial_safe
    from ohbot_chess.body import detect_headroll

    serial_safe.install(ohbot)
    ohbot.reset()
    print("Ohbot bringup\n")

    detected = detect_headroll(ohbot)
    print(f"Motor table says head roll is {'fitted' if detected else 'NOT fitted'}.")
    print("Watch the robot and confirm.\n")

    try:
        for motor in sorted(MOTOR_NAMES):
            if motor == ex.HEADROLL:
                continue
            sweep(ohbot, motor, MOTOR_NAMES[motor])

        print()
        sweep(ohbot, ex.HEADROLL, MOTOR_NAMES[ex.HEADROLL])
        rolled = ask("Did the head TILT sideways (ear towards shoulder)?")

        print()
        for name, colour in (("blue", (0, 0, 10)), ("amber", (10, 5, 0))):
            print(f"  eyes -> {name}")
            ohbot.setEyeColour(*colour)
            time.sleep(1.0)
        ohbot.setEyeColour(*config.EYE_COLOURS["off"])
        eyes = ask("Did the eyes light up and change colour?")

        print()
        print("Speech test.")
        ohbot.say("Hello. I am ready to play chess.")

    finally:
        ohbot.reset()
        time.sleep(0.5)
        ohbot.close()

    print("\n" + "=" * 60)
    if rolled != detected:
        print("NOTE: detection disagreed with what you saw. The override below")
        print("is what matters -- pass it every time.\n")

    flags = []
    if not rolled:
        flags.append("--headroll no")
        print("Head roll: NOT fitted.")
        print("  The sympathetic pose is rebuilt from lids and pitch instead.")
        print("  It reads as attentive rather than warm. That is expected.")
    else:
        print("Head roll: fitted. The head-cock is available.")

    if eyes:
        flags.append("--eyes")
        print("Illuminating Eyes: fitted.")
    else:
        print("Illuminating Eyes: not fitted (or not seen).")
        print("  Nothing is lost -- state is always carried by pose and speech")
        print("  as well, so colour is never the only signal.")

    print()
    print("Run the game with:")
    print(f"  python -m ohbot_chess.cli --teach {' '.join(flags)}".rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
