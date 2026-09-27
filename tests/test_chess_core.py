# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Engine, coach and game state.

Tested against a real Stockfish rather than a stub. A stub can confirm that the
code calls the engine; it cannot catch a sign error in centipawn loss, which is
the bug this module is most likely to have and did in fact have.
"""

from __future__ import annotations

import chess
import pytest

from ohbot_chess import config
from ohbot_chess.chess_core import Coach, Engine, EngineUnavailable, GameState

# -- game state -------------------------------------------------------------


def test_colours_and_turns() -> None:
    state = GameState("white")
    assert state.child_colour == chess.WHITE
    assert state.child_to_move
    assert not state.robot_to_move

    state.push(chess.Move.from_uci("e2e4"))
    assert state.robot_to_move


def test_black_child_moves_second() -> None:
    state = GameState("black")
    assert state.robot_to_move
    assert not state.child_to_move


def test_undo_takes_a_whole_pair() -> None:
    """Undoing one ply hands the turn to the wrong player."""
    state = GameState("white")
    state.push(chess.Move.from_uci("e2e4"))
    state.push(chess.Move.from_uci("e7e5"))
    assert state.undo_pair() == 2
    assert state.child_to_move


def test_undo_at_the_start_is_harmless() -> None:
    state = GameState("white")
    assert state.undo_pair() == 0
    assert state.fen == chess.Board().fen()


def test_position_readback_is_grouped_for_the_ear() -> None:
    """Sixty-four squares in file order is not followable by ear."""
    state = GameState("white")
    lines = state.describe_position()
    assert len(lines) == 2
    assert lines[0].startswith("White has")
    assert "and" in lines[0]


def test_result_from_the_childs_point_of_view() -> None:
    state = GameState("white")
    for uci in ("f2f3", "e7e5", "g2g4", "d8h4"):
        state.push(chess.Move.from_uci(uci))
    assert state.is_over
    assert state.result_for_child() == "loss"


# -- engine -----------------------------------------------------------------


def test_missing_binary_raises_something_actionable() -> None:
    with pytest.raises(EngineUnavailable) as excinfo:
        Engine(path="definitely-not-stockfish").open()
    assert "install" in str(excinfo.value).lower()


def test_engine_returns_a_legal_move(stockfish_path: str) -> None:
    state = GameState("white")
    state.push(chess.Move.from_uci("e2e4"))
    with Engine(stockfish_path, config.LEVELS["cub"], seed=1) as engine:
        move = engine.choose(state)
    assert move in state.board.legal_moves


def test_sharp_takes_the_top_candidate() -> None:
    """weakness 0.0 must always take the best of the candidate list.

    Asserted on the sampler rather than by comparing two engine calls: Stockfish
    carries its hash table between analyses, so asking the same question twice
    in one process can legitimately give two different best moves. Comparing
    those would test the engine's determinism, not this code's.
    """
    from ohbot_chess.chess_core import Candidate

    options = [
        Candidate(chess.Move.from_uci("e2e4"), 40),
        Candidate(chess.Move.from_uci("d2d4"), 20),
        Candidate(chess.Move.from_uci("a2a3"), -30),
    ]
    engine = Engine(path="unused", level=config.LEVELS["sharp"], seed=1)
    assert engine._sample(options, weakness=0.0) is options[0]


def test_sharp_chooses_from_the_engines_top_moves(stockfish_path: str) -> None:
    state = GameState("white")
    state.push(chess.Move.from_uci("e2e4"))
    with Engine(stockfish_path, config.LEVELS["sharp"], seed=1) as engine:
        top = {c.move for c in engine.candidates(state, 3, 12)}
        assert engine.choose(state) in top


def test_weakness_spreads_choices_down_the_list() -> None:
    """Otherwise the difficulty dial does nothing."""
    from ohbot_chess.chess_core import Candidate

    options = [Candidate(chess.Move.from_uci(u), 0) for u in ("e2e4", "d2d4", "a2a3", "h2h3")]
    engine = Engine(path="unused", level=config.LEVELS["kitten"], seed=4)
    picked = {engine._sample(options, weakness=0.95).move for _ in range(40)}
    assert len(picked) > 1


def test_weak_levels_do_not_always_pick_the_best(stockfish_path: str) -> None:
    """Otherwise the difficulty setting is decorative."""
    state = GameState("white")
    state.push(chess.Move.from_uci("e2e4"))
    with Engine(stockfish_path, config.LEVELS["kitten"], seed=3) as engine:
        best = engine.candidates(state, 1, config.LEVELS["kitten"].play_depth)[0].move
        chosen = {engine.choose(state) for _ in range(6)}
    assert chosen - {best}, "kitten always played the engine's best move"


def test_seed_makes_choice_reproducible(stockfish_path: str) -> None:
    """A demo you cannot reproduce is a demo you cannot debug."""
    state = GameState("white")
    state.push(chess.Move.from_uci("e2e4"))
    picks = []
    for _ in range(2):
        with Engine(stockfish_path, config.LEVELS["kitten"], seed=11) as engine:
            picks.append([engine.choose(state) for _ in range(4)])
    assert picks[0] == picks[1]


def test_weakening_never_hangs_mate(stockfish_path: str) -> None:
    """Losing on purpose is not gentleness, it is a broken opponent."""
    # Black to move, and several moves lose immediately to Qxf7#.
    state = GameState("black")
    board = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR b KQkq - 0 1")
    state.board = board
    with Engine(stockfish_path, config.LEVELS["kitten"], seed=5) as engine:
        for _ in range(5):
            move = engine.choose(state)
            board.push(move)
            assert not board.is_checkmate(), f"{move} walked into mate"
            board.pop()


def test_mercy_engages_when_the_child_is_lost(stockfish_path: str) -> None:
    state = GameState("black")
    # Black is a queen and a rook down.
    state.board = chess.Board("4k3/8/8/8/8/8/8/3QK2R w K - 0 1")
    with Engine(stockfish_path, config.LEVELS["fox"], mercy=True, seed=2) as engine:
        engine.choose(state)
        assert engine.mercy_active


def test_mercy_stays_off_in_a_level_game(stockfish_path: str) -> None:
    state = GameState("white")
    state.push(chess.Move.from_uci("e2e4"))
    with Engine(stockfish_path, config.LEVELS["fox"], mercy=True, seed=2) as engine:
        engine.choose(state)
        assert not engine.mercy_active


# -- coach ------------------------------------------------------------------


def test_blunder_is_recognised_as_such(stockfish_path: str) -> None:
    """Fool's Mate must not score as a great move.

    It did, because the fallback evaluation was taken from the opponent's point
    of view and max(0, ...) clamped the resulting nonsense to zero loss.
    """
    state = GameState("white")
    state.push(chess.Move.from_uci("f2f3"))
    state.push(chess.Move.from_uci("e7e5"))
    with Engine(stockfish_path, config.LEVELS["cub"]) as engine:
        judgement = Coach(engine).judge(state, chess.Move.from_uci("g2g4"))
    assert judgement.label == config.BLUNDER
    assert judgement.cp_loss > config.MISTAKE_CP


def test_judging_does_not_mutate_the_position(stockfish_path: str) -> None:
    state = GameState("white")
    before = state.fen
    with Engine(stockfish_path, config.LEVELS["cub"]) as engine:
        Coach(engine).judge(state, chess.Move.from_uci("a2a3"))
    assert state.fen == before


def test_good_move_is_not_called_a_blunder(stockfish_path: str) -> None:
    state = GameState("white")
    with Engine(stockfish_path, config.LEVELS["cub"]) as engine:
        judgement = Coach(engine).judge(state, chess.Move.from_uci("e2e4"))
    assert judgement.label in (config.GREAT, config.GOOD)


def test_forced_recapture_is_not_praised(stockfish_path: str) -> None:
    """Praising the only legal move is hollow, and children hear it as hollow."""
    state = GameState("white")
    state.board = chess.Board("4k3/8/8/8/8/8/6q1/7K w - - 0 1")
    only = list(state.board.legal_moves)
    assert len(only) < config.GREAT_NEEDS_ALTERNATIVES
    with Engine(stockfish_path, config.LEVELS["cub"]) as engine:
        judgement = Coach(engine).judge(state, only[0])
    assert judgement.label != config.GREAT


# -- restraint --------------------------------------------------------------


class _StubEngine:
    def candidates(self, *args: object, **kwargs: object) -> list[object]:
        return []


def test_blunders_always_get_a_word() -> None:
    coach = Coach(_StubEngine())  # type: ignore[arg-type]
    from ohbot_chess.chess_core import Judgement

    blunder = Judgement(config.BLUNDER, 900, "g4", "Nc3", 20)
    assert coach.should_comment(blunder, 5)
    assert coach.should_comment(blunder, 6), "a second blunder was let pass"


def test_praise_respects_the_cooldown() -> None:
    """A comment on every move turns the game into a lecture."""
    coach = Coach(_StubEngine())  # type: ignore[arg-type]
    from ohbot_chess.chess_core import Judgement

    great = Judgement(config.GREAT, 0, "e4", "e4", 20)
    assert coach.should_comment(great, 10)
    assert not coach.should_comment(great, 11)
    assert coach.should_comment(great, 10 + config.COACH_COOLDOWN_MOVES)


def test_ordinary_moves_pass_without_comment() -> None:
    coach = Coach(_StubEngine())  # type: ignore[arg-type]
    from ohbot_chess.chess_core import Judgement

    ordinary = Judgement(config.GOOD, 20, "Nf3", "Nf3", 20)
    assert not coach.should_comment(ordinary, 40)
