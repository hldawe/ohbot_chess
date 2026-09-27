# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Parsing: the module with the most ways to be quietly wrong."""

from __future__ import annotations

import chess
import pytest

from ohbot_chess import moves


@pytest.fixture
def start() -> chess.Board:
    return chess.Board()


# -- typed notation ---------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("e4", "e2e4"),
        ("Nf3", "g1f3"),
        ("e2e4", "e2e4"),
        ("g1f3", "g1f3"),
        ("  e4  ", "e2e4"),
    ],
)
def test_typed_notation(start: chess.Board, text: str, expected: str) -> None:
    parsed = moves.parse(text, start)
    assert parsed.ok
    assert parsed.move is not None
    assert parsed.move.uci() == expected


# -- spoken -----------------------------------------------------------------


@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("e four", "e2e4"),
        ("e two e four", "e2e4"),
        ("knight to f three", "g1f3"),
        ("night f three", "g1f3"),
        ("horse to f three", "g1f3"),
        ("pawn to e four", "e2e4"),
        ("d four please", "d2d4"),
    ],
)
def test_spoken_moves(start: chess.Board, spoken: str, expected: str) -> None:
    parsed = moves.parse(spoken, start)
    assert parsed.ok, f"{spoken!r} -> {parsed.kind}"
    assert parsed.move is not None
    assert parsed.move.uci() == expected


def test_rank_homophone_only_after_a_file(start: chess.Board) -> None:
    """'to' is a rank after a file letter and a preposition everywhere else.

    This is the whole reason normalisation is positional. Applied globally,
    "knight to f three" becomes "knight 2 f 3" and is lost.
    """
    assert moves.normalise_spoken("e to e four") == "e2 e4"
    assert moves.normalise_spoken("knight to f three") == "N f3"


@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("e for", "e4"),
        ("e ate", "e8"),
        ("b free", "b3"),
        ("a won", "a1"),
        ("c sicks", "c6"),
    ],
)
def test_number_homophones(spoken: str, expected: str) -> None:
    assert moves.normalise_spoken(spoken) == expected


def test_castling_phrases(start: chess.Board) -> None:
    assert moves.normalise_spoken("castle kingside") == "O-O"
    assert moves.normalise_spoken("long castle") == "O-O-O"
    assert moves.normalise_spoken("short castle") == "O-O"


def test_castling_parses_when_legal() -> None:
    board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    parsed = moves.parse("castle kingside", board)
    assert parsed.ok
    assert parsed.move is not None
    assert parsed.move.uci() == "e1g1"


# -- ambiguity --------------------------------------------------------------


def test_ambiguous_is_not_unknown() -> None:
    """Two knights reaching one square is an ambiguous POSITION.

    The child was perfectly clear. Reporting this as "I didn't catch that"
    blames the wrong party and is discouraging, so the two are distinct kinds.
    """
    board = chess.Board("4k3/8/8/8/8/8/8/1N1K1N2 w - - 0 1")
    parsed = moves.parse("knight to d two", board)
    assert parsed.kind == moves.AMBIGUOUS
    assert len(parsed.candidates) == 2
    assert {board.san(m) for m in parsed.candidates} == {"Nbd2", "Nfd2"}


def test_explicit_origin_resolves_ambiguity() -> None:
    board = chess.Board("4k3/8/8/8/8/8/8/1N1K1N2 w - - 0 1")
    parsed = moves.parse("b one d two", board)
    assert parsed.ok
    assert parsed.move is not None
    assert parsed.move.uci() == "b1d2"


def test_promotion_defaults_to_queen() -> None:
    board = chess.Board("8/4P3/8/8/8/8/8/4K1k1 w - - 0 1")
    parsed = moves.parse("e eight", board)
    assert parsed.ok
    assert parsed.move is not None
    assert parsed.move.promotion == chess.QUEEN


# -- illegal ----------------------------------------------------------------


def test_illegal_pawn_reach(start: chess.Board) -> None:
    parsed = moves.parse("e5", start)
    assert parsed.kind == moves.ILLEGAL
    assert "pawn" in moves.explain_illegal(parsed, start)


def test_illegal_own_piece_in_the_way(start: chess.Board) -> None:
    parsed = moves.parse("Ke2", start)
    assert "your own pawn" in moves.explain_illegal(parsed, start)


def test_illegal_blocked_slider(start: chess.Board) -> None:
    """A bishop aimed down a blocked diagonal is blocked, not incapable.

    board.attacks() stops at the blocker, so this needs checking against the
    unobstructed ray or the explanation degrades to a useless generic one.
    """
    parsed = moves.parse("Bb5", start)
    assert "in the way" in moves.explain_illegal(parsed, start)


def test_illegal_while_in_check_says_so() -> None:
    board = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    parsed = moves.parse("a3", board)
    assert parsed.kind == moves.ILLEGAL
    assert "check" in moves.explain_illegal(parsed, board)


def test_unknown_input(start: chess.Board) -> None:
    assert moves.parse("banana", start).kind == moves.UNKNOWN
    assert moves.parse("", start).kind == moves.UNKNOWN


# -- speaking ---------------------------------------------------------------


@pytest.mark.parametrize(
    "san,expected",
    [
        ("e4", "e four"),
        ("Nf3", "knight to f three"),
        ("Nxf3+", "knight takes f three, check"),
        ("Qh4#", "queen to h four, checkmate"),
        ("O-O", "castles kingside"),
        ("O-O-O", "castles queenside"),
        ("exd5", "e takes d five"),
    ],
)
def test_say_move(san: str, expected: str) -> None:
    assert moves.say_move(san) == expected


def test_say_move_disambiguator_is_speakable() -> None:
    """'knight from b to d seven' is not something anyone says."""
    assert moves.say_move("Nbd7") == "knight from the b file to d seven"


def test_say_square_uses_rank_words() -> None:
    """Digits leave verbalisation to the TTS engine; words do not."""
    assert moves.say_square("e4") == "e four"
    assert moves.say_square("h8") == "h eight"


def test_promotion_is_spoken() -> None:
    assert "promoting to a queen" in moves.say_move("e8=Q#")


# -- grammar ----------------------------------------------------------------


def test_spoken_forms_cover_the_phrasings(start: chess.Board) -> None:
    forms = moves.spoken_forms(chess.Move.from_uci("g1f3"), start)
    assert "knight f three" in forms
    assert "knight to f three" in forms
    assert "knight g one f three" in forms


def test_spoken_forms_are_parseable(start: chess.Board) -> None:
    """Every phrasing offered to the recogniser must parse back to its move.

    A grammar entry the parser then rejects is the worst possible failure: the
    child says exactly what she was told to say and is told it wasn't
    understood.
    """
    for move in start.legal_moves:
        for form in moves.spoken_forms(move, start):
            parsed = moves.parse(form, start)
            assert parsed.kind in (moves.MOVE, moves.AMBIGUOUS), (
                f"{form!r} for {move} -> {parsed.kind}"
            )
            if parsed.kind == moves.MOVE:
                assert parsed.move == move, f"{form!r} -> {parsed.move}, wanted {move}"
