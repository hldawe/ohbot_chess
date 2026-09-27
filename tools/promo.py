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
"""Ohbot reads a short promo for the Leeds Digital Festival family session.

    python tools/promo.py --mock          # read it on screen, no robot
    python tools/promo.py                 # perform it, with a countdown
    python tools/promo.py --beat 4        # redo one line
    python tools/promo.py --list          # the script, with timings

Not part of the chess app -- it just borrows its voice and its face.

FOR RECORDING

`--countdown` gives you time to start the camera and get out of shot; it
defaults to five seconds. Every line is a separate beat, so if one delivery is
poor you can redo that beat alone rather than the whole thing.

Numbers and dates are written out as WORDS in the script below. "27th" and
"9+" are read inconsistently by TTS engines, and a promo video is a bad place
to discover which way yours goes.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ohbot_chess import config, speech  # noqa: E402

# ---------------------------------------------------------------------------
# CHECK THIS BEFORE RECORDING.
#
# The event listing contradicts itself. Eventbrite's date and its page title
# both say SUNDAY 27 SEPTEMBER 2026, 10am to 12:30pm -- but the body copy, on
# both the Eventbrite page and the Leeds Digital Festival page, describes it as
# a "Saturday morning drop-in session". The Saturday that week is the 26th.
#
# The date below follows Eventbrite's structured data, since that is what
# drives the booking. Change it if the copy is the one that's right.
# ---------------------------------------------------------------------------
WHEN = "Sunday the twenty-seventh of September"

# Each beat is (text, pose, gesture). Gestures are sparing on purpose -- a
# robot that moves on every sentence reads as twitchy on camera, and the ones
# that land are the ones that are rare.
BEATS: list[tuple[str, str, str | None]] = [
    (
        "Hello. I'm Ohbot.",
        "pleased",
        "perk_up",
    ),
    (
        "I'm a robot head. I do exactly what I'm told, which is rather the point.",
        "playful",
        None,
    ),
    (
        f"On {WHEN}, I'll be at Leeds Trinity's city campus, "
        "on Trevelyan Square, along with a lot of my friends.",
        "neutral",
        None,
    ),
    (
        "It's a family session for the Leeds Digital Festival. "
        "You bring the family. You write the code. I do the talking.",
        "pleased",
        "nod",
    ),
    (
        "You'll code me using blocks, a bit like Scratch. "
        "You don't need to have written any code before.",
        "neutral",
        None,
    ),
    (
        "You could have me read a story out loud. Or ask you questions and keep the score.",
        "playful",
        "tilt",
    ),
    (
        "You can even play me at chess. I'll tell you my move, "
        "and you move the piece for me, because I haven't got any hands.",
        "playful",
        "look_away",
    ),
    (
        "Nobody is marking anything. It's a drop in, so come whenever suits you. "
        "Nine and over, with a grown up.",
        "neutral",
        None,
    ),
    (
        "Come along, and make me say something better than this.",
        "playful",
        "double_blink",
    ),
]


def full_text() -> str:
    return " ".join(text for text, _, _ in BEATS)


def estimate_seconds(text: str, words_per_minute: int = 150) -> float:
    """Rough spoken length. Piper's alba runs at about this pace."""
    return len(text.split()) / words_per_minute * 60


def show_script() -> None:
    total = 0.0
    for index, (text, pose, gesture) in enumerate(BEATS, start=1):
        seconds = estimate_seconds(text)
        total += seconds
        movement = f"{pose}" + (f" + {gesture}" if gesture else "")
        print(f"\n  [{index}] ~{seconds:4.1f}s  ({movement})")
        print(f"      {text}")
    words = len(full_text().split())
    print(f"\n  {words} words, roughly {total:.0f} seconds.\n")


def build_body(mock: bool, eyes: bool, headroll: str):  # type: ignore[no-untyped-def]
    from ohbot_chess.body import MockBody, OhbotBody

    if mock:
        return MockBody(verbose=True)
    return OhbotBody(
        idle=True,  # blinking between lines keeps it alive on camera
        has_headroll={"auto": None, "yes": True, "no": False}[headroll],
        has_eyes=eyes,
    )


def install_voice(mock: bool, voice: str, voice_dir: str) -> None:
    if mock:
        return
    try:
        speech.install(speech.PiperTTS(voice, voice_dir))
    except Exception as e:
        print(f"[speech] falling back to the built-in voice: {e}", file=sys.stderr)
        print("[speech] that will NOT be the Scottish voice.", file=sys.stderr)


def perform(body, beats, countdown: float, gap: float) -> None:  # type: ignore[no-untyped-def]
    if countdown:
        print(f"\nStarting in {countdown:.0f} seconds. Roll camera.")
        for remaining in range(int(countdown), 0, -1):
            print(f"  {remaining}...", flush=True)
            time.sleep(1)
        print("  go\n")

    body.look_at("child")
    for index, (text, pose, gesture) in enumerate(beats, start=1):
        print(f"[{index}] {text}")
        body.speak(text, pose=pose, gesture=gesture)
        time.sleep(gap)  # a breath between lines; also gives you an edit point

    body.express("neutral")
    body.look_at("child")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true", help="print it, no robot")
    parser.add_argument("--list", action="store_true", help="show the script and timings")
    parser.add_argument("--beat", type=int, default=None, help="perform a single beat (1-based)")
    parser.add_argument("--countdown", type=float, default=5.0)
    parser.add_argument("--gap", type=float, default=0.6, help="pause between lines")
    parser.add_argument("--voice", default=config.DEFAULT_VOICE)
    parser.add_argument("--voice-dir", default="voices")
    parser.add_argument("--eyes", action="store_true")
    parser.add_argument("--headroll", choices=["auto", "yes", "no"], default="auto")
    parser.add_argument("--wav", default=None, help="render to a WAV instead of speaking")
    args = parser.parse_args()

    if args.list:
        show_script()
        return 0

    if args.wav:
        # Audio only, for cutting under other footage.
        try:
            engine = speech.PiperTTS(args.voice, args.voice_dir)
        except speech.VoiceUnavailable as e:
            print(e, file=sys.stderr)
            return 2
        engine.synth(full_text(), args.wav)
        print(f"Written to {args.wav}")
        return 0

    beats = BEATS
    if args.beat is not None:
        if not 1 <= args.beat <= len(BEATS):
            print(f"--beat must be between 1 and {len(BEATS)}", file=sys.stderr)
            return 2
        beats = [BEATS[args.beat - 1]]

    install_voice(args.mock, args.voice, args.voice_dir)
    with build_body(args.mock, args.eyes, args.headroll) as body:
        perform(body, beats, args.countdown if not args.mock else 0, args.gap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
