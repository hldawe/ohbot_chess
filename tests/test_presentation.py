# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The presentation layer: chess events becoming faces, gestures and words."""

from __future__ import annotations

import chess

from ohbot_chess import config, phrases
from ohbot_chess.body import MockBody
from ohbot_chess.chess_core import GameState, Judgement
from ohbot_chess.presentation import Presenter


def presenter(body: MockBody) -> Presenter:
    return Presenter(body)


# -- restraint --------------------------------------------------------------


def test_routine_announcement_has_no_gesture(mock_body: MockBody) -> None:
    """A gesture on every move looks twitchy.

    The budget is spent on the coaching beats that earn it, not on saying which
    square a knight went to.
    """
    state = GameState("white")
    state.push(chess.Move.from_uci("e2e4"))
    move = chess.Move.from_uci("e7e5")

    presenter(mock_body).announce(state, move, state.san(move))
    assert mock_body.gestures == []
    assert mock_body.said


def test_blunder_gets_both_a_face_and_a_movement(mock_body: MockBody) -> None:
    """A pose alone reads as static; a gesture alone reads as a tic."""
    judgement = Judgement(config.BLUNDER, 900, "g4", "Nc3", 20)
    presenter(mock_body).coach(judgement, 5)

    assert "sympathetic" in mock_body.poses
    assert "slow_nod" in mock_body.gestures


def test_judgement_mapping_is_coherent(mock_body: MockBody) -> None:
    """Bad news must never arrive on a bright face."""
    bad = Judgement(config.BLUNDER, 900, "g4", "Nc3", 20)
    good = Judgement(config.GREAT, 0, "Nc3", "Nc3", 20)

    presenter(mock_body).coach(bad, 1)
    assert mock_body.poses[-1] in ("sympathetic", "concerned")

    body = MockBody(verbose=False)
    presenter(body).coach(good, 1)
    assert body.poses[-1] in ("impressed", "pleased")


# -- the eye-colour rule ----------------------------------------------------


def test_state_is_never_signalled_by_colour_alone(mock_body: MockBody) -> None:
    """The Illuminating Eyes accessory cannot be detected and may be absent.

    So every state change must ALSO carry a pose or an utterance, or a robot
    without the accessory silently stops telling you what it is doing.
    """
    presenter(mock_body).thinking(True)
    assert "thinking" in mock_body.states
    assert "thinking" in mock_body.poses, "thinking was signalled by colour alone"

    body = MockBody(verbose=False)
    presenter(body).invite(1)
    assert "your_turn" in body.states
    assert body.said, "your turn was signalled by colour alone"


# -- gaze -------------------------------------------------------------------


def test_announcement_looks_at_the_square_then_the_child(mock_body: MockBody) -> None:
    """The gaze sequence is what this hardware can do that Reachy Mini could not.

    Uncalibrated it resolves to a fixed downward direction, so the call is
    harmless either way -- but the call site has to exist from day one or
    retrofitting it means touching every announcement path.
    """
    state = GameState("white")
    state.push(chess.Move.from_uci("e2e4"))
    move = chess.Move.from_uci("g8f6")

    presenter(mock_body).announce(state, move, state.san(move))
    assert len(mock_body.gazes) >= 2
    assert mock_body.gazes[-1] == (5, 6)  # back to the child


def test_gaze_uses_calibration_when_present() -> None:
    from ohbot_chess import expression as ex

    body = MockBody(verbose=False)
    body.board_gaze = ex.BoardGaze(a1=(8.0, 1.0), h8=(2.0, 4.0))

    state = GameState("white")
    state.push(chess.Move.from_uci("e2e4"))
    move = chess.Move.from_uci("g8f6")
    presenter(body).announce(state, move, state.san(move))

    assert body.gazes[0] != ex.LOOK_DIRECTIONS["board"]


# -- input problems ---------------------------------------------------------


def test_ambiguous_offers_the_options(mock_body: MockBody) -> None:
    from ohbot_chess import moves

    board = chess.Board("4k3/8/8/8/8/8/8/1N1K1N2 w - - 0 1")
    parsed = moves.parse("knight to d two", board)
    presenter(mock_body).ambiguous(parsed, board, 1)

    # Origin squares, not disambiguated SAN: the person is looking at a board,
    # not at notation.
    spoken = " ".join(mock_body.said)
    assert "knight" in spoken
    assert "b one" in spoken and "f one" in spoken


def test_illegal_gives_the_reason_not_just_a_refusal(mock_body: MockBody) -> None:
    from ohbot_chess import moves

    board = chess.Board()
    parsed = moves.parse("Bb5", board)
    presenter(mock_body).illegal(parsed, board, 1)

    assert "in the way" in " ".join(mock_body.said)


# -- board readback ---------------------------------------------------------


def test_confirmation_names_both_squares(mock_body: MockBody) -> None:
    """The echo is the only check that what was heard is what was meant.

    "e four. Good." cannot catch a move that parsed to a different legal move
    than intended -- the robot's board is then internally consistent and simply
    wrong, which is the hardest kind of desync to trace.
    """
    from ohbot_chess import moves as moves_module

    board = chess.Board()
    move = chess.Move.from_uci("g1f3")
    presenter(mock_body).confirm(moves_module.narrate(move, board), 1)

    spoken = " ".join(mock_body.said)
    assert "g one" in spoken and "f three" in spoken


def test_undo_names_the_moves_it_takes_back(mock_body: MockBody) -> None:
    """An undo pops TWO plies. Reverse only your own move on the physical board
    and you are out by one piece, with nothing said on either side."""
    presenter(mock_body).undone(["pawn on e two to e four", "pawn on e seven to e five"], 1)

    spoken = " ".join(mock_body.said)
    assert "e two to e four" in spoken
    assert "e seven to e five" in spoken


def test_readback_spells_squares_for_speech(mock_body: MockBody) -> None:
    """'a1' left as-is is read aloud inconsistently by TTS engines."""
    state = GameState("white")
    presenter(mock_body).read_board(state)

    spoken = " ".join(mock_body.said)
    assert "e one" in spoken
    assert "a1" not in spoken


def test_readback_returns_the_gaze_to_the_child(mock_body: MockBody) -> None:
    state = GameState("white")
    presenter(mock_body).read_board(state)
    assert mock_body.gazes[-1] == (5, 6)


# -- endings ----------------------------------------------------------------


def test_child_win_is_celebrated(mock_body: MockBody) -> None:
    state = GameState("white")
    for uci in ("e2e4", "f7f6", "d2d4", "g7g5", "d1h5"):
        state.push(chess.Move.from_uci(uci))
    assert state.is_over and state.result_for_child() == "win"

    presenter(mock_body).game_over(state)
    assert mock_body.poses[-1] == "impressed"


def test_robot_win_is_not_gloated_over(mock_body: MockBody) -> None:
    state = GameState("white")
    for uci in ("f2f3", "e7e5", "g2g4", "d8h4"):
        state.push(chess.Move.from_uci(uci))
    assert state.result_for_child() == "loss"

    presenter(mock_body).game_over(state)
    spoken = " ".join(mock_body.said).lower()
    assert "good game" in spoken or "thank you" in spoken
    assert mock_body.poses[-1] != "impressed"


def test_stalemate_is_distinguished_from_a_loss(mock_body: MockBody) -> None:
    state = GameState("white")
    state.board = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert state.board.is_stalemate()

    presenter(mock_body).game_over(state)
    assert "draw" in " ".join(mock_body.said).lower()


# -- phrase integrity -------------------------------------------------------


def test_every_phrase_bank_fills_its_placeholders() -> None:
    """A phrase missing a key must not take the game down mid-move."""
    banks = {
        "ANNOUNCE": {"move": "e four"},
        "ANNOUNCE_CAPTURE": {"move": "e four"},
        "ANNOUNCE_CHECK": {"move": "e four"},
        "ANNOUNCE_CASTLE": {"move": "castles kingside"},
        "ANNOUNCE_PROMOTE": {"move": "e eight"},
        "CONFIRM": {"move": "pawn on e two to e four"},
        "REPEAT": {"move": "pawn on e two to e four"},
        "UNDO": {"moves": "e four and e five"},
        "TRY_ANOTHER": {},
        "REWIND": {},
        "ILLEGAL": {"reason": "it is blocked"},
        "AMBIGUOUS": {"piece": "knight", "options": "b one or f one"},
        "GAME_START": {"colour": "white", "first": "You go first."},
    }
    for name, kwargs in banks.items():
        bank = getattr(phrases, name)
        for index in range(len(bank)):
            filled = phrases.pick(bank, index, **kwargs)
            assert "{" not in filled, f"{name}[{index}] left a placeholder"
            assert filled.strip()


def test_selection_is_deterministic() -> None:
    """A demo you cannot reproduce is a demo you cannot debug."""
    first = phrases.pick(phrases.ANNOUNCE, 3, move="e four")
    second = phrases.pick(phrases.ANNOUNCE, 3, move="e four")
    assert first == second


def test_selection_rotates_rather_than_repeating() -> None:
    seen = {phrases.pick(phrases.YOUR_TURN, i) for i in range(len(phrases.YOUR_TURN))}
    assert len(seen) == len(phrases.YOUR_TURN)


def test_every_coaching_band_has_wording() -> None:
    for label in config.JUDGEMENTS:
        assert phrases.coaching(label, 0, best="Nc3"), f"no phrasing for {label}"


def test_coaching_tone_avoids_blunt_labels() -> None:
    """The word 'blunder' at a beginner is a knock, not a lesson."""
    for index in range(len(phrases.COACHING[config.BLUNDER])):
        line = phrases.coaching(config.BLUNDER, index, best="Nc3").lower()
        assert "blunder" not in line
        assert "stupid" not in line and "bad move" not in line
