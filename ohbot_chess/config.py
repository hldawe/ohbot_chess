# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings: difficulty levels, coaching thresholds, timings.

Two things here are deliberately independent, and conflating them was a
constraint of the previous hardware rather than a design choice:

  * How WELL the engine plays        -- Level.candidates / Level.weakness
  * How WELL the engine understands  -- ANALYSIS_DEPTH

On a battery-powered robot those competed for one CPU budget, so weakening play
also weakened the coaching. Tethered to a laptop they don't compete, so the
coach can analyse at full strength while the opponent plays like a kitten.
That is the right way round: bad play is the point, bad advice never is.
"""

from __future__ import annotations

from dataclasses import dataclass

# -- difficulty -------------------------------------------------------------


@dataclass(frozen=True)
class Level:
    """One difficulty setting.

    candidates: how many engine moves to consider (multipv width).
    weakness:   0.0 always plays the best of them, 1.0 spreads evenly across
                all of them. Values in between bias towards the better end.

    Weakening by SAMPLING rather than by limiting depth is deliberate. A
    depth-limited engine blunders tactically while still crushing you
    positionally, which plays like nothing human and teaches nothing. Sampling
    a merely-worse move from a full-strength candidate list plays like a person
    having an off day.
    """

    name: str
    label: str  # how the robot says it aloud
    play_depth: int
    candidates: int
    weakness: float
    description: str


LEVELS: dict[str, Level] = {
    "kitten": Level(
        name="kitten",
        label="kitten",
        play_depth=6,
        candidates=8,
        weakness=0.95,
        description="Very gentle. Will miss things on purpose.",
    ),
    "cub": Level(
        name="cub",
        label="cub",
        play_depth=8,
        candidates=6,
        weakness=0.75,
        description="Gentle, but will punish a free piece.",
    ),
    "fox": Level(
        name="fox",
        label="fox",
        play_depth=10,
        candidates=4,
        weakness=0.45,
        description="Plays properly most of the time.",
    ),
    "owl": Level(
        name="owl",
        label="owl",
        play_depth=12,
        candidates=3,
        weakness=0.20,
        description="Strong. Rarely gives anything away.",
    ),
    "sharp": Level(
        name="sharp",
        label="sharp",
        play_depth=14,
        candidates=1,
        weakness=0.0,
        description="Full strength. Not recommended for a first game.",
    ),
}

DEFAULT_LEVEL = "cub"
LEVEL_ORDER = ["kitten", "cub", "fox", "owl", "sharp"]


def level(name: str) -> Level:
    try:
        return LEVELS[name]
    except KeyError:
        raise KeyError(
            "Unknown level {!r}. Available: {}".format(name, ", ".join(LEVEL_ORDER))
        ) from None


# -- mercy ------------------------------------------------------------------
#
# When the child is already losing badly, playing on at full strength is not a
# lesson, it is a rout. Mercy widens the candidate list and raises weakness, so
# the engine quietly eases off. It never announces this.

MERCY_ENABLED = True
# Child's evaluation, in centipawns, below which mercy engages.
MERCY_THRESHOLD_CP = -400
# How much weakness increases while mercy is active (capped at 1.0).
MERCY_WEAKNESS_BONUS = 0.25
# Extra candidates to consider while mercy is active.
MERCY_EXTRA_CANDIDATES = 3

# -- analysis and coaching --------------------------------------------------

# Depth used for JUDGING moves, independent of the level's play_depth.
# The host machine can afford this; the CM4 could not.
ANALYSIS_DEPTH = 14

# Centipawn loss bands. A move's loss is (best eval) - (eval after the move
# played), from the mover's point of view, so loss is always >= 0.
#
# These are deliberately more forgiving than an adult analysis tool. Telling a
# beginner that a move costing 60 centipawns was a mistake is technically true
# and pedagogically useless.
GREAT_CP = 5
GOOD_CP = 45
INACCURACY_CP = 110
MISTAKE_CP = 250
# Anything above MISTAKE_CP is a blunder.

# Judgement labels, in order of increasing badness.
GREAT = "great"
GOOD = "good"
INACCURACY = "inaccuracy"
MISTAKE = "mistake"
BLUNDER = "blunder"

JUDGEMENTS = [GREAT, GOOD, INACCURACY, MISTAKE, BLUNDER]

# Coaching restraint. Commenting on every move turns the game into a lecture
# and drains the meaning from the comments that matter. Blunders always get a
# word; anything else waits for the cooldown.
COACH_ALWAYS = {BLUNDER}
COACH_COOLDOWN_MOVES = 3

# A move is only ever called "great" if there was something to miss -- praising
# the only legal recapture is transparently hollow and children notice.
GREAT_NEEDS_ALTERNATIVES = 2

# -- timing -----------------------------------------------------------------

# How long to wait, after announcing its own move, before asking whether the
# piece has been moved. Impatience here was a real bug on the previous build:
# the robot asked while the child's hand was still over the board.
PATIENCE_SECONDS = 12.0
# Gap between subsequent nudges, once the first has been given.
NUDGE_INTERVAL_SECONDS = 20.0

# Speech-recognition patience: how long to wait for an utterance before
# offering the keyboard.
LISTEN_TIMEOUT_SECONDS = 30.0

# -- speech -----------------------------------------------------------------

# Piper, not Kokoro. Kokoro has no Scottish voice -- its British voices are RP.
# Voice consistency across robots matters more than the marginal speed.
DEFAULT_VOICE = "en_GB-alba-medium"

# The ohbot viseme loop iterates range(0, length - chunk, chunk) and then
# indexes times[-1]. Audio shorter than about 0.2s leaves that list empty and
# say() raises IndexError. "Check." is a realistic utterance, so every clip
# gets a silent tail.
TAIL_SILENCE_SECONDS = 0.3

# -- speech recognition -----------------------------------------------------

VOSK_MODEL_DIR = "model"
SAMPLE_RATE = 16000
BLOCK = 4000
# Speech must be this much louder than the calibrated room noise.
NOISE_MULTIPLIER = 3.0
NOISE_FLOOR = 0.004
SILENCE_SECONDS = 1.0
MIN_SPEECH_SECONDS = 0.3
CALIBRATION_SECONDS = 1.0

# -- robot ------------------------------------------------------------------

BLINK_INTERVAL = (2.0, 6.0)
DRIFT_INTERVAL = (5.0, 11.0)
BACKCHANNEL_INTERVAL = (3.0, 7.0)

# Eye colours as (r, g, b), 0-10 each. Requires the Illuminating Eyes
# accessory; without it these are harmless no-ops. Never the sole signal of
# any state -- see expression.py.
EYE_COLOURS = {
    "listening": (0, 0, 10),
    "thinking": (10, 5, 0),
    "speaking": (0, 10, 3),
    "your_turn": (0, 8, 8),
    "off": (0, 0, 0),
}

GAZE_CALIBRATION_FILE = "gaze_calibration.json"
