# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""ohbot_chess -- chess with a robot that has no hands.

    from ohbot_chess import GameState, Engine, Coach, Presenter, Game
    from ohbot_chess.body import MockBody

    state = GameState("white")
    with Engine("stockfish") as engine, MockBody() as body:
        Game(state, engine, Presenter(body), KeyboardInput()).play()

Ohbot computes the moves and reads the board; the person opposite moves the
pieces for both players. Everything runs locally -- Stockfish, Vosk and Piper
are all on this machine, and nothing is sent anywhere.

`body`, `listener` and `speech` are deliberately NOT imported here. Each pulls
in hardware or model dependencies that a typed, mocked or tested run has no use
for, so importing this package costs nothing but python-chess.
"""

from __future__ import annotations

from . import config, expression, moves, phrases
from .chess_core import (
    Coach,
    Engine,
    EngineUnavailable,
    GameState,
    Judgement,
)
from .game import (
    Game,
    Input,
    KeyboardInput,
    ScriptedInput,
    VoiceInput,
    describe_result,
)
from .presentation import Presenter

__version__ = "1.0.0"

__all__ = [
    "Coach",
    "Engine",
    "EngineUnavailable",
    "Game",
    "GameState",
    "Input",
    "Judgement",
    "KeyboardInput",
    "Presenter",
    "ScriptedInput",
    "VoiceInput",
    "config",
    "describe_result",
    "expression",
    "moves",
    "phrases",
    "__version__",
]
