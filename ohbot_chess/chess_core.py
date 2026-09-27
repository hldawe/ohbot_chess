# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Game state, the engine wrapper, and the coach.

This module knows nothing about robots, speech or expression. It is pure chess
and it is the part that ports unchanged between bodies.

Three objects:

    GameState -- the position, whose turn it is, and the move history
    Engine    -- Stockfish, deliberately weakened by sampling (see config.Level)
    Coach     -- judges a move by centipawn loss, at full analysis strength
"""

from __future__ import annotations

import contextlib
import random
from collections.abc import Collection
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal

import chess
import chess.engine

from . import config


class EngineUnavailable(RuntimeError):
    """Raised when the Stockfish binary cannot be started."""


# -- game state -------------------------------------------------------------


class GameState:
    """The position and its history.

    Thin wrapper over chess.Board. It exists so the rest of the app never
    imports python-chess directly, which keeps the surface small and means a
    board desync recovery (undo, readback) has one place to live.
    """

    def __init__(self, child_plays: str = "white") -> None:
        if child_plays not in ("white", "black"):
            raise ValueError("child_plays must be 'white' or 'black'")
        self.board = chess.Board()
        self.child_colour = chess.WHITE if child_plays == "white" else chess.BLACK
        self.robot_colour = not self.child_colour

    # -- turns ---------------------------------------------------------

    @property
    def child_to_move(self) -> bool:
        return self.board.turn == self.child_colour

    @property
    def robot_to_move(self) -> bool:
        return self.board.turn == self.robot_colour

    @property
    def move_number(self) -> int:
        return self.board.fullmove_number

    # -- moving --------------------------------------------------------

    def legal_moves(self) -> list[chess.Move]:
        return list(self.board.legal_moves)

    def san(self, move: chess.Move) -> str:
        """Standard algebraic notation for a move in the CURRENT position."""
        return self.board.san(move)

    def push(self, move: chess.Move) -> str:
        """Play a move, returning its SAN as it was before being played."""
        san = self.board.san(move)
        self.board.push(move)
        return san

    def undo_pair(self) -> int:
        """Take back one full move pair, so it is the same player's turn again.

        Returns how many plies were actually undone (0, 1 or 2). Undoing a
        single ply would hand the turn to the wrong player, so both come off
        unless there is only one to take.
        """
        undone = 0
        for _ in range(2):
            if not self.board.move_stack:
                break
            self.board.pop()
            undone += 1
        return undone

    # -- status --------------------------------------------------------

    @property
    def is_over(self) -> bool:
        return self.board.is_game_over()

    def outcome(self) -> chess.Outcome | None:
        return self.board.outcome()

    def result_for_child(self) -> str:
        """'win' | 'loss' | 'draw' | 'unfinished'."""
        outcome = self.board.outcome()
        if outcome is None:
            return "unfinished"
        if outcome.winner is None:
            return "draw"
        return "win" if outcome.winner == self.child_colour else "loss"

    @property
    def fen(self) -> str:
        return self.board.fen()

    def describe_position(self) -> list[str]:
        """The position in plain words, for reading aloud when boards diverge.

        Grouped by colour and piece type rather than square by square: "White
        has a king on g one, a rook on f one..." is followable by ear, whereas
        sixty-four squares in file order is not.
        """
        lines = []
        for colour, name in ((chess.WHITE, "White"), (chess.BLACK, "Black")):
            parts = []
            for piece_type in (
                chess.KING,
                chess.QUEEN,
                chess.ROOK,
                chess.BISHOP,
                chess.KNIGHT,
                chess.PAWN,
            ):
                squares = sorted(self.board.pieces(piece_type, colour))
                if not squares:
                    continue
                piece_name = chess.piece_name(piece_type)
                plural = piece_name if len(squares) == 1 else piece_name + "s"
                named = [chess.square_name(s) for s in squares]
                parts.append(f"{plural} on {_join(named)}")
            if parts:
                lines.append(f"{name} has {_join(parts)}.")
        return lines


def _join(items: list[str]) -> str:
    """Join for speech: 'a, b and c' rather than 'a, b, c'."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


# -- engine -----------------------------------------------------------------


@dataclass
class Candidate:
    """One engine-suggested move with its evaluation, from the mover's view."""

    move: chess.Move
    score_cp: int
    mate_in: int | None = None


class Engine:
    """Stockfish, weakened by sampling rather than by crippling search.

    Used as a context manager so the subprocess is always cleaned up:

        with Engine(path, level) as engine:
            move = engine.choose(state)
    """

    def __init__(
        self,
        path: str = "stockfish",
        level: config.Level | None = None,
        analysis_depth: int = config.ANALYSIS_DEPTH,
        mercy: bool = config.MERCY_ENABLED,
        seed: int | None = None,
    ) -> None:
        self.path = path
        self.level = level or config.LEVELS[config.DEFAULT_LEVEL]
        self.analysis_depth = analysis_depth
        self.mercy = mercy
        self._rng = random.Random(seed)
        self._engine: Any = None
        self.mercy_active = False

    # -- lifecycle -----------------------------------------------------

    def __enter__(self) -> Engine:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        self.close()
        return False

    def open(self) -> None:
        try:
            self._engine = chess.engine.SimpleEngine.popen_uci(self.path)
        except (OSError, chess.engine.EngineError) as e:
            raise EngineUnavailable(
                f"Could not start Stockfish at {self.path!r}.\n"
                "Install it (brew install stockfish / apt install stockfish) "
                "or pass --stockfish /path/to/binary."
            ) from e

    def close(self) -> None:
        if self._engine is not None:
            # A dead subprocess is already closed as far as we care; failing to
            # quit it must not mask whatever error is being unwound.
            with contextlib.suppress(Exception):
                self._engine.quit()
            self._engine = None

    def _require(self) -> Any:
        if self._engine is None:
            raise EngineUnavailable("Engine is not open. Call open() first.")
        return self._engine

    # -- analysis ------------------------------------------------------

    def candidates(self, state: GameState, count: int, depth: int) -> list[Candidate]:
        """Top `count` moves in the current position, best first.

        Scores are from the point of view of the side to move, so a larger
        score is always better for whoever is choosing.
        """
        engine = self._require()
        if state.board.is_game_over():
            return []

        infos = engine.analyse(
            state.board,
            chess.engine.Limit(depth=depth),
            multipv=max(1, count),
        )
        if isinstance(infos, dict):  # multipv=1 can return a bare dict
            infos = [infos]

        out: list[Candidate] = []
        for info in infos:
            pv = info.get("pv")
            if not pv:
                continue
            score = info["score"].pov(state.board.turn)
            out.append(
                Candidate(
                    move=pv[0],
                    score_cp=score.score(mate_score=100_000),
                    mate_in=score.mate(),
                )
            )
        return out

    def evaluate(self, state: GameState, colour: bool) -> int:
        """Evaluation in centipawns from `colour`'s point of view."""
        engine = self._require()
        if state.board.is_game_over():
            outcome = state.board.outcome()
            if outcome is None or outcome.winner is None:
                return 0
            return 100_000 if outcome.winner == colour else -100_000
        info = engine.analyse(state.board, chess.engine.Limit(depth=self.analysis_depth))
        return int(info["score"].pov(colour).score(mate_score=100_000))

    # -- move choice ---------------------------------------------------

    def choose(self, state: GameState, exclude: Collection[chess.Move] = ()) -> chess.Move | None:
        """Pick the robot's move at the configured strength.

        Mercy is checked first and silently widens the sampling if the child is
        already well behind. The robot never says it is going easy -- being
        told you are being pitied is worse than losing.

        `exclude` holds moves the person has said cannot be played on the
        physical board. Those moves are legal in the position this code thinks
        it is in, so nothing here can detect the problem -- only a person can.
        Returns None when every candidate has been refused, which means the two
        boards disagree about more than one piece and guessing again is
        pointless.
        """
        width = self.level.candidates
        weakness = self.level.weakness

        self.mercy_active = False
        if self.mercy and self._child_is_struggling(state):
            self.mercy_active = True
            width += config.MERCY_EXTRA_CANDIDATES
            weakness = min(1.0, weakness + config.MERCY_WEAKNESS_BONUS)

        options = self.candidates(state, width, self.level.play_depth)
        if not options:
            raise EngineUnavailable("Engine returned no candidate moves.")

        if exclude:
            options = [o for o in options if o.move not in exclude]
            if not options:
                # Widen once before giving up: the shortlist for this level may
                # simply be shorter than the number of refusals.
                every = self.candidates(state, 20, self.level.play_depth)
                options = [o for o in every if o.move not in exclude]
            if not options:
                return None

        return self._sample(options, weakness).move

    def _child_is_struggling(self, state: GameState) -> bool:
        return self.evaluate(state, state.child_colour) < config.MERCY_THRESHOLD_CP

    def _sample(self, options: list[Candidate], weakness: float) -> Candidate:
        """Choose from the candidate list, biased towards the better end.

        weakness 0.0 always returns the best move. 1.0 spreads evenly. In
        between, weights decay geometrically down the list, so a mediocre move
        is common and a terrible one is rare -- which is how a weak human
        plays, and unlike a random mover, which is merely annoying.
        """
        if weakness <= 0.0 or len(options) == 1:
            return options[0]

        # Weights decay geometrically down the candidate list, and `decay` IS
        # the weakness -- high weakness gives near-flat weights and therefore a
        # real chance of a worse move, low weakness gives a steep curve that
        # nearly always lands on the best.
        #
        # Inverting this (decay = 1 - weakness) makes kitten the STRONGEST
        # setting, because 0.95 weakness becomes a decay of 0.05 and the top
        # move gets twenty times the weight of the second. Every level then
        # plays at full strength, and against a live engine the effect hides
        # behind Stockfish's own move-to-move variation.
        decay = min(max(weakness, 0.01), 0.99)
        weights = [decay**i for i in range(len(options))]

        # Never pick a move that hangs mate when a non-losing one exists.
        # Losing on purpose is not gentleness, it is a broken opponent.
        safe = [
            (opt, w)
            for opt, w in zip(options, weights, strict=True)
            if not (opt.mate_in is not None and opt.mate_in < 0)
        ]
        if safe:
            picks, weights = [s[0] for s in safe], [s[1] for s in safe]
        else:
            picks = options

        return self._rng.choices(picks, weights=weights, k=1)[0]


# -- coach ------------------------------------------------------------------


@dataclass
class Judgement:
    """The verdict on one move."""

    label: str  # config.GREAT .. config.BLUNDER
    cp_loss: int
    played_san: str
    best_san: str | None
    alternatives: int
    missed_mate: bool = False

    @property
    def is_notable(self) -> bool:
        return self.label in (config.GREAT, config.MISTAKE, config.BLUNDER)


class Coach:
    """Judges the child's moves at full analysis strength.

    Deliberately separate from the playing engine's strength. The opponent may
    be a kitten; the teacher never is.
    """

    def __init__(self, engine: Engine, depth: int = config.ANALYSIS_DEPTH) -> None:
        self.engine = engine
        self.depth = depth
        self._last_comment_move = -config.COACH_COOLDOWN_MOVES

    def judge(self, state: GameState, move: chess.Move) -> Judgement:
        """Judge `move` in `state`, BEFORE it is played.

        The state is not mutated: the move is pushed and popped internally.
        """
        options = self.engine.candidates(state, 4, self.depth)
        played_san = state.san(move)

        if not options:
            return Judgement(config.GOOD, 0, played_san, None, 0)

        best = options[0]
        best_san = state.san(best.move)
        alternatives = len(state.legal_moves())

        played = next((o for o in options if o.move == move), None)
        if played is not None:
            played_cp = played.score_cp
        else:
            # Not in the top-n: evaluate it directly, from the MOVER's point of
            # view. Getting this sign wrong scores Fool's Mate as a great move,
            # because max(0, ...) then clamps the nonsense to zero loss.
            mover = state.board.turn
            state.board.push(move)
            try:
                played_cp = self.engine.evaluate(state, mover)
            finally:
                state.board.pop()

        cp_loss = max(0, best.score_cp - played_cp)
        missed_mate = (
            best.mate_in is not None
            and best.mate_in > 0
            and (played is None or played.mate_in is None or played.mate_in <= 0)
        )

        return Judgement(
            label=self._label(cp_loss, alternatives),
            cp_loss=cp_loss,
            played_san=played_san,
            best_san=best_san,
            alternatives=alternatives,
            missed_mate=missed_mate,
        )

    def _label(self, cp_loss: int, alternatives: int) -> str:
        if cp_loss <= config.GREAT_CP:
            # Praising the only legal recapture is hollow, and children hear it
            # as hollow. A "great" move needs something it could have got wrong.
            if alternatives < config.GREAT_NEEDS_ALTERNATIVES:
                return config.GOOD
            return config.GREAT
        if cp_loss <= config.GOOD_CP:
            return config.GOOD
        if cp_loss <= config.INACCURACY_CP:
            return config.INACCURACY
        if cp_loss <= config.MISTAKE_CP:
            return config.MISTAKE
        return config.BLUNDER

    def should_comment(self, judgement: Judgement, move_number: int) -> bool:
        """Whether this judgement is worth saying out loud.

        Restraint is the point. Blunders always get a word, because letting one
        pass silently teaches nothing. Everything else waits for the cooldown,
        so praise stays scarce enough to mean something.
        """
        if judgement.label in config.COACH_ALWAYS:
            self._last_comment_move = move_number
            return True
        if not judgement.is_notable:
            return False
        if move_number - self._last_comment_move < config.COACH_COOLDOWN_MOVES:
            return False
        self._last_comment_move = move_number
        return True

    def reset(self) -> None:
        self._last_comment_move = -config.COACH_COOLDOWN_MOVES
