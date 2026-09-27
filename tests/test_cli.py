# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The command line: argument wiring and the decisions made before a game starts."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ohbot_chess import cli, config
from ohbot_chess import expression as ex


def parse(argv: list[str]) -> Any:
    return cli.build_parser().parse_args(argv)


# -- defaults ---------------------------------------------------------------


def test_defaults_are_the_gentle_ones() -> None:
    """A first game should not open on full strength."""
    args = parse([])
    assert args.level == config.DEFAULT_LEVEL
    assert args.level != "sharp"
    assert args.child_plays == "white"
    assert not args.speech


def test_analysis_depth_is_independent_of_level() -> None:
    """The opponent may be a kitten; the teacher never is.

    On the previous hardware these competed for one CPU budget, so weakening
    play also weakened the coaching. Tethered, they do not compete.
    """
    args = parse(["--level", "kitten"])
    assert args.analysis_depth == config.ANALYSIS_DEPTH
    assert args.analysis_depth > config.LEVELS["kitten"].play_depth


def test_analysis_depth_can_be_set_separately() -> None:
    args = parse(["--level", "sharp", "--analysis-depth", "20"])
    assert args.analysis_depth == 20


def test_unknown_level_is_rejected_at_the_boundary() -> None:
    with pytest.raises(SystemExit):
        parse(["--level", "grandmaster"])


# -- the hardware unknowns --------------------------------------------------


def test_headroll_defaults_to_detection() -> None:
    assert parse([]).headroll == "auto"


@pytest.mark.parametrize("flag,expected", [("yes", True), ("no", False), ("auto", None)])
def test_headroll_override_maps_to_a_tristate(flag: str, expected: bool | None) -> None:
    """None means detect; True/False is an explicit override for when it's wrong."""
    args = parse(["--headroll", flag])
    assert {"auto": None, "yes": True, "no": False}[args.headroll] is expected


def test_eyes_are_off_unless_declared() -> None:
    """The accessory cannot be detected, so it has to be asserted."""
    assert not parse([]).eyes
    assert parse(["--eyes"]).eyes


# -- gaze calibration -------------------------------------------------------


def test_absent_calibration_is_not_an_error(tmp_path: Any) -> None:
    """Uncalibrated is a shipping state, not a failure."""
    gaze = cli.load_gaze(str(tmp_path / "nothing.json"))
    assert not gaze.calibrated
    assert gaze.square("e4") == ex.LOOK_DIRECTIONS["board"]


def test_calibration_is_loaded_when_present(tmp_path: Any) -> None:
    path = tmp_path / "gaze.json"
    path.write_text(json.dumps({"a1": [8.0, 1.0], "h8": [2.0, 4.0]}))

    gaze = cli.load_gaze(str(path))
    assert gaze.calibrated
    assert gaze.square("a1") == (8.0, 1.0)


def test_corrupt_calibration_degrades_rather_than_crashing(tmp_path: Any, capsys: Any) -> None:
    """A miscalibrated gaze is worse than none, and a crash before a game is
    worse still. Warn and carry on looking at the board in general."""
    path = tmp_path / "gaze.json"
    path.write_text("{not json")

    gaze = cli.load_gaze(str(path))
    assert not gaze.calibrated
    assert "gaze" in capsys.readouterr().err


def test_partial_calibration_is_rejected(tmp_path: Any) -> None:
    path = tmp_path / "gaze.json"
    path.write_text(json.dumps({"a1": [8.0, 1.0]}))
    assert not cli.load_gaze(str(path)).calibrated


# -- degradation ------------------------------------------------------------


def test_missing_voice_costs_the_accent_not_the_game(monkeypatch: Any, capsys: Any) -> None:
    """A missing model file should degrade the demo, not stop it."""

    def explode(*args: Any, **kwargs: Any) -> None:
        raise cli.speech.VoiceUnavailable("no voice here")

    monkeypatch.setattr(cli.speech, "PiperTTS", explode)
    cli.install_voice(parse([]))

    assert "built-in voice" in capsys.readouterr().err


def test_mock_mode_skips_voice_installation(monkeypatch: Any) -> None:
    called = []
    monkeypatch.setattr(cli.speech, "PiperTTS", lambda *a, **k: called.append(1))
    cli.install_voice(parse(["--mock"]))
    assert not called


def test_speech_failure_falls_back_to_the_keyboard(monkeypatch: Any, capsys: Any) -> None:
    """Being stuck with a robot that cannot hear you and will not let you type
    is worse than any recognition error."""
    import ohbot_chess.listener as listener_module

    def explode(*args: Any, **kwargs: Any) -> None:
        raise listener_module.VoskUnavailable("no model")

    monkeypatch.setattr(listener_module, "Listener", explode)
    source = cli.build_input(parse(["--speech"]))

    from ohbot_chess.game import KeyboardInput

    assert isinstance(source, KeyboardInput)
    assert "keyboard" in capsys.readouterr().err


def test_keyboard_is_the_default_input() -> None:
    from ohbot_chess.game import KeyboardInput

    assert isinstance(cli.build_input(parse([])), KeyboardInput)


def test_mock_body_is_built_for_mock_runs() -> None:
    from ohbot_chess.body import MockBody

    assert isinstance(cli.build_body(parse(["--mock"])), MockBody)


def test_missing_stockfish_exits_with_a_code_not_a_traceback(capsys: Any) -> None:
    code = cli.main(["--mock", "--stockfish", "definitely-not-stockfish"])
    assert code == 2
    assert "install" in capsys.readouterr().err.lower()
