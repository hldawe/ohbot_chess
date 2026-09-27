# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The listener's pure parts -- grammar construction and the control branch.

Capture and recognition need a microphone and a 40 MB model, so they are not
exercised here. Everything that decides WHAT the recogniser is allowed to
return is pure, and that is the part with the safety property worth testing.
"""

from __future__ import annotations

import json

import chess

from ohbot_chess import listener, moves
from ohbot_chess.chess_core import GameState

# -- grammar ----------------------------------------------------------------


def test_grammar_is_valid_json_and_a_list() -> None:
    parsed = json.loads(listener.build_grammar(["e four", "knight to f three"]))
    assert isinstance(parsed, list)
    assert all(isinstance(item, str) for item in parsed)


def test_grammar_is_deduplicated_and_lowercased() -> None:
    parsed = json.loads(listener.build_grammar(["E Four", "e four", "e four "]))
    assert parsed.count("e four") == 1


def test_grammar_drops_blanks() -> None:
    parsed = json.loads(listener.build_grammar(["", "   ", "e four"]))
    assert "" not in parsed and "   " not in parsed


def test_grammar_from_a_real_position_excludes_illegal_moves() -> None:
    """The safety property this whole choice of recogniser exists for.

    With a closed grammar the recogniser cannot return a move that cannot be
    played. An open-vocabulary model can, and its most dangerous output is a
    confident transcription of a plausible wrong move.
    """
    state = GameState("white")
    phrases = []
    for move in state.legal_moves():
        phrases.extend(moves.spoken_forms(move, state.board))
    grammar = json.loads(listener.build_grammar(phrases))

    assert "e four" in grammar
    assert "knight to f three" in grammar
    # f6 is Black's square; White cannot reach it on move one.
    assert "knight to f six" not in grammar
    assert "queen to h five" not in grammar


def test_grammar_narrows_when_the_position_does() -> None:
    """Fewer legal moves must mean a smaller grammar.

    Note this tracks the NUMBER of legal moves, not how open the board looks: a
    lone rook on an empty board has more moves than the opening position, and
    therefore a larger grammar. So the comparison is against a position with
    exactly one legal reply.
    """
    opening = GameState("white")
    forced = GameState("white")
    forced.board = chess.Board("7k/8/8/8/8/8/6q1/7K w - - 0 1")
    assert len(forced.legal_moves()) == 1

    def size(state: GameState) -> int:
        phrases: list[str] = []
        for move in state.legal_moves():
            phrases.extend(moves.spoken_forms(move, state.board))
        return len(json.loads(listener.build_grammar(phrases)))

    assert size(forced) < size(opening)


# -- control words ----------------------------------------------------------


def test_control_words_are_matched_before_any_parsing() -> None:
    """`stop` must never reach a parser that might see a move in it."""
    assert listener.control_word("stop") == "stop"
    assert listener.control_word("STOP") == "stop"
    assert listener.control_word(" stop ") == "stop"


def test_control_word_returns_none_for_anything_else() -> None:
    assert listener.control_word("e four") is None
    assert listener.control_word("") is None
    assert listener.control_word(None) is None  # type: ignore[arg-type]


def test_confirmation_phrasings_are_generous() -> None:
    """With no camera this is the only way it learns its move was made."""
    for said in ("done", "moved", "moved it", "okay", "yes", "finished"):
        assert listener.control_word(said) == "done"


def test_every_control_word_maps_to_a_known_command() -> None:
    known = {
        "repeat",
        "board",
        "undo",
        "help",
        "resign",
        "stop",
        "done",
        "cannot",
        "show",
        "fix",
        "correct",
    }
    assert set(listener.CONTROL_WORDS.values()) <= known
