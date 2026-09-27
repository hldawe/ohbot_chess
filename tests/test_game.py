# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The turn loop, driven by scripted input so the whole game runs in CI."""

from __future__ import annotations

from typing import Any

import chess
import pytest

from ohbot_chess import config, moves, phrases
from ohbot_chess import listener as listener_mod
from ohbot_chess.body import MockBody
from ohbot_chess.chess_core import Coach, Engine, GameState
from ohbot_chess.game import Game, ScriptedInput, describe_result
from ohbot_chess.presentation import Presenter


class FixedEngine:
    """An engine that plays a scripted reply. Keeps loop tests off Stockfish."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.mercy_active = False
        self.excluded: list[set[chess.Move]] = []

    def choose(self, state: GameState, exclude: Any = ()) -> chess.Move | None:
        self.excluded.append(set(exclude))
        if self.replies:
            move = state.board.parse_san(self.replies.pop(0))
            if move not in set(exclude):
                return move
        for move in state.board.legal_moves:
            if move not in set(exclude):
                return move
        return None

    def candidates(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    def close(self) -> None:
        pass


def _said_one_of(body: MockBody, bank: list[str]) -> bool:
    """Whether the robot said any line from a phrase bank.

    Phrase selection rotates, so which line comes out depends on the move
    number. Testing the bank tests the behaviour; testing one line tests the
    ordering of a list.
    """
    spoken = " ".join(body.said)
    return any(_stem(line) in spoken for line in bank)


def _stem(phrase: str) -> str:
    """The part of a phrase before any placeholder, which is enough to match."""
    return phrase.split("{")[0].strip() or phrase


def build(
    script: list[str],
    replies: list[str] | None = None,
    child: str = "white",
    blocking: bool = True,
    coach: Coach | None = None,
) -> tuple[Game, MockBody, GameState, ScriptedInput]:
    state = GameState(child)
    body = MockBody(verbose=False)
    source = ScriptedInput(script, blocking=blocking)
    game = Game(
        state=state,
        engine=FixedEngine(replies),  # type: ignore[arg-type]
        presenter=Presenter(body),
        source=source,
        coach=coach,
        teach=coach is not None,
        sleep=lambda _: None,
    )
    return game, body, state, source


# -- a whole game -----------------------------------------------------------


def test_a_scripted_game_plays_to_checkmate() -> None:
    """Scholar's mate, delivered by the child."""
    game, body, state, _ = build(
        script=["e4", "", "Bc4", "", "Qh5", "", "Qxf7"],
        replies=["e5", "Nc6", "Nf6"],
    )
    result = game.play()

    assert state.board.is_checkmate()
    assert result == "win"
    assert "checkmate" in " ".join(body.said).lower()


def test_the_robot_asks_for_its_move_to_be_made() -> None:
    """The defining constraint: it has no hands.

    Its move is not something it makes, it is something it asks for.
    """
    game, body, _, _ = build(script=["e4", "", "stop"], replies=["e5"])
    game.play()

    spoken = " ".join(body.said).lower()
    assert "move it" in spoken or "move that" in spoken


def test_result_line_is_not_what_is_spoken() -> None:
    game, _, state, _ = build(script=["stop"])
    game.play()
    assert describe_result(state) == "Game stopped."


# -- input handling ---------------------------------------------------------


def test_illegal_move_is_explained_and_retried() -> None:
    game, body, state, _ = build(script=["e5", "e4", "", "stop"], replies=["e5"])
    game.play()

    spoken = " ".join(body.said).lower()
    assert "pawn" in spoken
    assert state.board.move_stack, "the retry never landed"


def test_ambiguous_move_asks_which_one() -> None:
    game, body, state, _ = build(script=["knight to d two", "b one d two", "", "stop"])
    state.board = chess.Board("4k3/8/8/8/8/8/8/1N1K1N2 w - - 0 1")
    game.play()

    spoken = " ".join(body.said)
    assert "b one" in spoken and "f one" in spoken


def test_unrecognised_input_asks_again_rather_than_guessing() -> None:
    game, body, state, _ = build(script=["banana", "e4", "", "stop"], replies=["e5"])
    game.play()

    # Asserted against the phrase bank rather than a chosen wording: selection
    # rotates deterministically, so pinning one line makes the test fail if the
    # bank is reordered, which is not a behaviour change.
    assert _said_one_of(body, phrases.NOT_UNDERSTOOD)
    assert state.board.move_stack, "the retry never landed"


def test_silence_never_becomes_a_move() -> None:
    """A timeout must be indistinguishable from a wrong guess in its effect."""
    game, _, state, _ = build(script=["", "", "stop"], blocking=False)
    game.play()
    assert not state.board.move_stack


# -- control words ----------------------------------------------------------


def test_board_readback_does_not_consume_the_turn() -> None:
    game, body, state, _ = build(script=["board", "e4", "", "stop"], replies=["e5"])
    game.play()

    assert "position" in " ".join(body.said).lower()
    assert state.board.move_stack


def test_undo_takes_back_a_whole_pair() -> None:
    game, _, state, _ = build(
        script=["e4", "", "d4", "", "take that back", "stop"],
        replies=["e5", "d5"],
    )
    game.play()

    # Two pairs played, one taken back.
    assert len(state.board.move_stack) == 2
    assert state.child_to_move


def test_resign_ends_the_game_gracefully() -> None:
    game, body, _, _ = build(script=["resign"])
    result = game.play()

    assert result == "unfinished"
    assert "good game" in " ".join(body.said).lower()


def test_help_lists_what_can_be_said() -> None:
    game, body, _, _ = build(script=["help", "stop"])
    game.play()
    assert "board" in " ".join(body.said).lower()


def test_stop_is_never_parsed_as_a_move() -> None:
    """`stop` must be unambiguous, so it never reaches the move parser."""
    assert listener_mod.control_word("stop") == "stop"
    game, _, state, _ = build(script=["stop"])
    game.play()
    assert not state.board.move_stack


# -- waiting for hands ------------------------------------------------------


def test_repeat_re_announces_the_move() -> None:
    """The commonest reason for a pause is forgetting what was asked for."""
    game, body, _, _ = build(script=["e4", "again", "", "stop"], replies=["e5"])
    game.play()

    assert sum("e five" in line for line in body.said) >= 2


def test_typed_empty_line_means_done() -> None:
    game, _, state, _ = build(script=["e4", "", "stop"], replies=["e5"], blocking=True)
    game.play()
    assert len(state.board.move_stack) == 2


def test_silence_from_a_microphone_does_not_mean_done() -> None:
    """The two cases are opposite and must not be conflated.

    A typed empty line is someone pressing Enter. An empty return from a
    microphone is a hand still busy on the board -- treating it as
    confirmation would race ahead of the physical game.
    """
    game, body, _, _ = build(script=["e4", "", "", "", "stop"], replies=["e5"], blocking=False)
    game.patience = 0.0  # elapse immediately so the nudge is observable
    game.play()

    assert _said_one_of(body, phrases.NUDGE)


def test_nudging_is_patient_by_default() -> None:
    """Impatience here was a real bug: it asked while a hand was mid-reach."""
    game, body, _, _ = build(script=["e4", "", "stop"], replies=["e5"], blocking=False)
    game.play()

    assert not any("have you" in line.lower() for line in body.said)


# -- the per-turn grammar ---------------------------------------------------


def test_grammar_is_rebuilt_from_the_legal_moves() -> None:
    """This is what makes an illegal move unrecognisable rather than merely
    rejected. A stale grammar is worse than none: confidently wrong."""
    game, _, _, source = build(script=["e4", "", "stop"], replies=["e5"])
    game.play()

    first_turn = source.asked[0]
    assert "knight to f three" in first_turn
    assert "e four" in first_turn
    # Nothing illegal in the opening position can be offered.
    assert "knight to f six" not in first_turn


def test_grammar_changes_as_the_position_does() -> None:
    game, _, _, source = build(script=["e4", "", "d4", "", "stop"], replies=["e5", "d5"])
    game.play()

    assert source.asked[0] != source.asked[-1]


def test_grammar_always_carries_the_control_words() -> None:
    grammar = listener_mod.build_grammar(["e four"])
    for word in ("stop", "board", "again", "help", "resign"):
        assert f'"{word}"' in grammar


def test_grammar_includes_the_unknown_token() -> None:
    """Without [unk] the recogniser must return SOMETHING from the list.

    A cough then becomes a move. With it, unrecognised audio comes back as
    unknown and the robot asks again.
    """
    assert "[unk]" in listener_mod.build_grammar(["e four"])


# -- coaching integration ---------------------------------------------------


def test_coaching_happens_before_the_move_is_played(stockfish_path: str) -> None:
    """The coach needs the position the decision was made in."""
    with Engine(stockfish_path, config.LEVELS["cub"]) as engine:
        coach = Coach(engine)
        game, body, state, _ = build(
            script=["f3", "", "g4", "", "stop"], replies=["e5"], coach=coach
        )
        game.engine = FixedEngine(["e5"])  # type: ignore[assignment]
        game.play()

    spoken = " ".join(body.said).lower()
    assert "careful" in spoken or "watch out" in spoken or "costs you" in spoken


def test_no_coaching_when_teaching_is_off() -> None:
    game, body, _, _ = build(script=["e4", "", "stop"], replies=["e5"], coach=None)
    game.play()
    assert not any("best move" in line.lower() for line in body.said)


# -- control word mapping ---------------------------------------------------


@pytest.mark.parametrize(
    "said,expected",
    [
        ("again", "repeat"),
        ("Repeat", "repeat"),
        ("take that back", "undo"),
        ("board", "board"),
        ("i resign", "resign"),
        ("done", "done"),
        ("moved it", "done"),
        ("  stop  ", "stop"),
    ],
)
def test_control_words(said: str, expected: str) -> None:
    assert listener_mod.control_word(said) == expected


def test_a_move_is_not_a_control_word() -> None:
    assert listener_mod.control_word("e four") is None
    assert listener_mod.control_word("knight to f three") is None


def test_control_words_do_not_collide_with_spoken_moves() -> None:
    """A control word that is also a legal phrasing would be unreachable.

    Whichever branch ran first would swallow the other, and which one that is
    would depend on the position.
    """
    board = chess.Board()
    for word in listener_mod.CONTROL_WORDS:
        parsed = moves.parse(word, board)
        assert not parsed.ok, f"{word!r} parses as {parsed.move}"


# -- rejecting a move the physical board cannot accept ----------------------


def test_saying_a_move_is_illegal_withdraws_it() -> None:
    """The failure that ruined a real game.

    The engine cannot produce an illegal move, but it CAN ask for one that is
    impossible on the physical board, because the two boards have drifted
    apart. With no camera only a person can notice, so there has to be
    something to say -- and before this, there was not.
    """
    game, body, state, _ = build(
        script=["e4", "that's not legal", "", "stop"], replies=["e5", "Nc6"]
    )
    game.play()

    # It withdrew e5 and asked for something else.
    played = [m.uci() for m in state.board.move_stack]
    assert "e7e5" not in played, "the refused move was played anyway"
    assert any("sorry" in line.lower() for line in body.said)


def test_a_refused_move_is_never_offered_again() -> None:
    game, _, _, _ = build(
        script=["e4", "illegal", "illegal", "", "stop"],
        replies=["e5", "e5", "Nc6"],
    )
    game.play()

    engine = game.engine
    assert engine.excluded[-1], "nothing was excluded on the retry"
    assert len(engine.excluded[-1]) >= 1


def test_refusing_everything_falls_back_to_reading_the_board() -> None:
    """Two boards disagreeing about one piece is recoverable by guessing again.

    This many refusals means they disagree about several, and guessing on is
    wasting the person's time.
    """

    class NeverSatisfied:
        mercy_active = False

        def choose(self, state: GameState, exclude: Any = ()) -> chess.Move | None:
            return None

        def candidates(self, *a: Any, **k: Any) -> list[Any]:
            return []

    game, body, _, _ = build(script=["e4", "", "stop"], replies=["e5"])
    game.engine = NeverSatisfied()  # type: ignore[assignment]
    game.play()

    spoken = " ".join(body.said).lower()
    assert "out of step" in spoken or "not matching up" in spoken
    assert "white has" in spoken, "it did not read the position out"


def test_unrecognised_words_while_waiting_are_not_confirmation() -> None:
    """This is what swallowed the protest.

    Anything unrecognised used to mean "yes, done", so telling the robot its
    move was impossible read as confirmation and it played on regardless.
    """
    game, body, state, _ = build(script=["e4", "wibble wobble", "", "stop"], replies=["e5"])
    game.play()

    assert _said_one_of(body, phrases.NOT_UNDERSTOOD_WAITING)


def test_undo_while_waiting_returns_the_turn() -> None:
    game, _, state, _ = build(script=["e4", "take that back", "stop"], replies=["e5"])
    game.play()

    assert not state.board.move_stack
    assert state.child_to_move


def test_refusal_phrasings_all_map_to_cannot() -> None:
    for said in (
        "that's not legal",
        "thats not legal.",
        "illegal",
        "I can't do that",
        "cant do that",
        "try another",
        "impossible!",
    ):
        assert listener_mod.control_word(said) == "cannot", said


def test_refusal_words_are_not_legal_moves() -> None:
    """A refusal that also parses as a move would be unreachable."""
    board = chess.Board()
    for word, command in listener_mod.CONTROL_WORDS.items():
        if command != "cannot":
            continue
        assert not moves.parse(word, board).ok, word
