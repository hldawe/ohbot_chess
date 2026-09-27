# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line entry point.

python -m ohbot_chess.cli --mock --level cub
python -m ohbot_chess.cli --level fox --teach --speech --vosk-model ./model
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from . import config, speech
from . import expression as ex
from .chess_core import Coach, Engine, EngineUnavailable, GameState
from .game import Game, KeyboardInput, VoiceInput, describe_result
from .journal import Journal
from .presentation import Presenter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ohbot_chess",
        description="Play chess with an Ohbot. It has no hands, so you move the pieces.",
    )
    parser.add_argument(
        "--level",
        default=config.DEFAULT_LEVEL,
        choices=config.LEVEL_ORDER,
        help="difficulty (default: %(default)s)",
    )
    parser.add_argument(
        "--child-plays",
        default="white",
        choices=["white", "black"],
        help="which colour the person plays (default: %(default)s)",
    )
    parser.add_argument("--teach", action="store_true", help="comment on your moves")
    parser.add_argument(
        "--no-mercy",
        action="store_true",
        help="don't ease off when the game is already lost",
    )
    parser.add_argument("--stockfish", default="stockfish", help="path to the binary")
    parser.add_argument(
        "--analysis-depth",
        type=int,
        default=config.ANALYSIS_DEPTH,
        help="depth used for JUDGING moves, independent of --level (default: %(default)s)",
    )
    parser.add_argument("--seed", type=int, default=None, help="reproducible move choice")

    parser.add_argument(
        "--no-board",
        action="store_true",
        help="don't print the board after each move",
    )
    parser.add_argument(
        "--ascii",
        action="store_true",
        help="letters instead of chess glyphs, for terminals that render them badly",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="don't write a game log",
    )
    parser.add_argument("--log-dir", default="logs", help="where game logs go")

    parser.add_argument("--mock", action="store_true", help="run with no robot")
    parser.add_argument(
        "--headroll",
        choices=["auto", "yes", "no"],
        default="auto",
        help="head-roll servo fitted (default: detect)",
    )
    parser.add_argument(
        "--eyes",
        action="store_true",
        help="the Illuminating Eyes accessory is fitted (cannot be detected)",
    )
    parser.add_argument("--no-idle", action="store_true", help="disable idle motion")

    parser.add_argument("--speech", action="store_true", help="listen for spoken moves")
    parser.add_argument("--vosk-model", default=config.VOSK_MODEL_DIR)
    parser.add_argument("--mic", type=int, default=None, help="input device index")
    parser.add_argument("--voice", default=config.DEFAULT_VOICE)
    parser.add_argument("--voice-dir", default="voices")
    parser.add_argument("--no-tts", action="store_true", help="use the built-in voice")
    parser.add_argument(
        "--gaze-calibration",
        default=config.GAZE_CALIBRATION_FILE,
        help="board corner calibration; absent means look at the board generally",
    )
    return parser


def load_gaze(path: str) -> ex.BoardGaze:
    """Load the board calibration, or return an uncalibrated map.

    Uncalibrated is a legitimate state, not an error: every square resolves to
    a fixed downward direction and the robot looks at the board rather than at
    a specific square.
    """
    if not path or not os.path.exists(path):
        return ex.BoardGaze()
    try:
        with open(path) as handle:
            return ex.BoardGaze.from_dict(json.load(handle))
    except (OSError, ValueError) as e:
        print(f"[gaze] ignoring {path}: {e}", file=sys.stderr)
        return ex.BoardGaze()


def build_body(args: argparse.Namespace) -> Any:
    from .body import MockBody, OhbotBody

    if args.mock:
        return MockBody()

    headroll = {"auto": None, "yes": True, "no": False}[args.headroll]
    return OhbotBody(
        idle=not args.no_idle,
        has_headroll=headroll,
        has_eyes=args.eyes,
        board_gaze=load_gaze(args.gaze_calibration),
    )


def install_voice(args: argparse.Namespace) -> None:
    """Install Piper, degrading to the built-in voice rather than failing.

    A missing voice file should cost the accent, not the game.
    """
    if args.mock or args.no_tts:
        return
    try:
        speech.install(speech.PiperTTS(args.voice, args.voice_dir))
    except Exception as e:
        print(f"[speech] using the built-in voice: {e}", file=sys.stderr)


def build_input(args: argparse.Namespace) -> Any:
    if not args.speech:
        return KeyboardInput()
    try:
        from .listener import Listener

        listener = Listener(model_dir=args.vosk_model, device=args.mic)
        listener.calibrate()
        return VoiceInput(listener)
    except Exception as e:
        print(f"[voice] falling back to the keyboard: {e}", file=sys.stderr)
        return KeyboardInput()


def build_screen(args: argparse.Namespace) -> Any:
    """A callable that prints the board, or None if that is switched off."""
    if args.no_board:
        return None

    def screen(text: str) -> None:
        print("\n" + text + "\n")

    return screen


def build_editor(args: argparse.Namespace) -> Any:
    """A callable that opens the position editor and returns a board or None."""

    def edit(board: Any, orientation: bool) -> Any:
        from .editor import PositionEditor

        return PositionEditor(board, orientation=orientation, unicode=not args.ascii).run()

    return edit


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    state = GameState(args.child_plays)
    try:
        engine = Engine(
            path=args.stockfish,
            level=config.level(args.level),
            analysis_depth=args.analysis_depth,
            mercy=not args.no_mercy,
            seed=args.seed,
        )
        engine.open()
    except EngineUnavailable as e:
        print(e, file=sys.stderr)
        return 2

    install_voice(args)
    source = build_input(args)

    journal = Journal(directory=args.log_dir, enabled=not args.no_log)
    journal.start(
        level=args.level,
        child_plays=args.child_plays,
        teach=args.teach,
        speech=args.speech,
        mock=args.mock,
        seed=args.seed,
        White="Player" if args.child_plays == "white" else "Ohbot",
        Black="Ohbot" if args.child_plays == "white" else "Player",
    )
    if not args.no_log:
        print(f"[log] {journal.where()}")

    try:
        with build_body(args) as body:
            if not args.mock:
                _report_hardware(body)
            presenter = Presenter(body)
            coach = Coach(engine, depth=args.analysis_depth) if args.teach else None
            game = Game(
                state=state,
                engine=engine,
                presenter=presenter,
                source=source,
                coach=coach,
                teach=args.teach,
                journal=journal,
                screen=build_screen(args),
                editor=build_editor(args),
            )
            game.play()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        engine.close()
        source.close()

    print(describe_result(state))
    print(state.fen)
    if not args.no_log:
        print(f"[log] {journal.where()}")
    return 0


def _report_hardware(body: Any) -> None:
    roll = "fitted" if body.has_headroll else "not fitted (poses adjusted)"
    eyes = "fitted" if body.has_eyes else "not in use"
    gaze = "calibrated" if body.board_gaze.calibrated else "uncalibrated"
    print(f"[robot] head roll: {roll}; eye LEDs: {eyes}; board gaze: {gaze}")


if __name__ == "__main__":
    raise SystemExit(main())
