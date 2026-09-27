# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning chess events into things the robot says and does.

This layer knows about chess but not about servos; body.py knows about servos
but not about chess. Everything that decides "a blunder gets a sympathetic face
and a slow nod" lives here, and nothing that decides which motor that means
does.

EXPRESSION IS DRIVEN BY GAME STATE, NOT BY A MODEL. The mapping below is a
lookup table. It is auditable, instant, and cannot decide that losing your
queen is exciting.

RESTRAINT IS ENFORCED HERE, not left to taste. A gesture on every move looks
twitchy and drains the meaning from the ones that matter, so routine
announcements get a face and no gesture, and the gesture budget is spent on the
moments that earn it.
"""

from __future__ import annotations

import chess

from . import config, moves, phrases
from .body import Body
from .chess_core import GameState, Judgement

# What each judgement looks like on the face. Poses and gestures both, because
# a pose alone reads as static and a gesture alone reads as a tic.
JUDGEMENT_EXPRESSION = {
    config.GREAT: ("impressed", "perk_up"),
    config.GOOD: ("pleased", None),
    config.INACCURACY: ("neutral", None),
    config.MISTAKE: ("concerned", "tilt"),
    config.BLUNDER: ("sympathetic", "slow_nod"),
}


class Presenter:
    """Everything the robot says and does, in chess terms."""

    def __init__(self, body: Body, speak_squares: bool = True) -> None:
        self.body = body
        # Whether to look at the square being discussed. Harmless when the
        # board is uncalibrated -- look_at_square falls back to a fixed
        # downward direction -- so this stays on by default.
        self.speak_squares = speak_squares

    # -- lifecycle -----------------------------------------------------

    def greet(self, state: GameState) -> None:
        self.body.look_at("child")
        self.body.speak(phrases.pick(phrases.GREETING), pose="pleased", gesture="perk_up")
        self.body.speak(phrases.pick(phrases.EXPLAIN_ROLE), pose="neutral")

        colour = "white" if state.child_colour == chess.WHITE else "black"
        first = "You go first." if state.child_to_move else "I'll go first."
        self.body.speak(
            phrases.pick(phrases.GAME_START, colour=colour, first=first),
            pose="pleased",
        )

    def farewell(self) -> None:
        self.body.look_at("child")
        self.body.speak(phrases.pick(phrases.GOODBYE), pose="pleased", gesture="nod")

    # -- the robot's move ----------------------------------------------

    def announce(self, state: GameState, move: chess.Move, san: str) -> None:
        """Say the robot's own move and ask for it to be played.

        The gaze sequence is the point: look at the destination square while
        naming it, then back at the child when handing the turn over. That is
        the thing this hardware can do that the previous one could not.
        """
        # narrate() rather than say_move(): it names the ORIGIN square too, so
        # the announcement can be checked against the physical board as it is
        # heard rather than five moves later.
        spoken = moves.narrate(move, state.board)
        bank = self._announce_bank(state, move, san)

        if self.speak_squares:
            self.body.look_at_square(chess.square_name(move.to_square))

        self.body.speak(
            phrases.pick(bank, state.move_number, move=spoken),
            pose="playful" if "#" in san else "neutral",
        )

        self.body.look_at("child")
        self.body.speak(phrases.pick(phrases.ASK_TO_MOVE, state.move_number))

    def _announce_bank(self, state: GameState, move: chess.Move, san: str) -> list[str]:
        if san.startswith("O-O"):
            return phrases.ANNOUNCE_CASTLE
        if "=" in san:
            return phrases.ANNOUNCE_PROMOTE
        if san.endswith("+"):
            return phrases.ANNOUNCE_CHECK
        if "x" in san:
            return phrases.ANNOUNCE_CAPTURE
        return phrases.ANNOUNCE

    def repeat_move(self, spoken: str, move_number: int) -> None:
        self.body.speak(
            phrases.pick(phrases.REPEAT, move_number, move=spoken),
            pose="neutral",
        )

    def try_another(self, move_number: int) -> None:
        """Acknowledge that the move it asked for cannot be played.

        The robot is at fault here, so it apologises and moves on rather than
        asking the person to double-check. Being told to look again when you
        have just looked is infuriating.
        """
        self.body.look_at("child")
        self.body.speak(
            phrases.pick(phrases.TRY_ANOTHER, move_number),
            pose="concerned",
            gesture="look_away",
        )

    def rewind_after_refusal(self, plies: int, move_number: int) -> None:
        bank = phrases.REWIND if plies else phrases.NOTHING_TO_REWIND
        self.body.look_at("child")
        self.body.speak(phrases.pick(bank, move_number), pose="concerned", gesture="look_away")

    def out_of_ideas(self) -> None:
        """Give up guessing and read the board out instead."""
        self.body.look_at("child")
        self.body.speak(phrases.pick(phrases.OUT_OF_IDEAS), pose="concerned")

    def not_understood_while_waiting(self, move_number: int) -> None:
        self.body.speak(
            phrases.pick(phrases.NOT_UNDERSTOOD_WAITING, move_number),
            pose="neutral",
            gesture="double_blink",
        )

    def nudge(self, move_number: int) -> None:
        """Ask whether the piece has been moved yet. Only after real patience."""
        self.body.look_at("child")
        self.body.speak(phrases.pick(phrases.NUDGE, move_number), pose="neutral")

    # -- the child's move ----------------------------------------------

    def invite(self, move_number: int) -> None:
        self.body.set_state("your_turn")
        self.body.look_at("child")
        self.body.speak(phrases.pick(phrases.YOUR_TURN, move_number), pose="neutral")
        self.body.attend(True)

    def confirm(self, spoken: str, move_number: int) -> None:
        """Echo the person's move back, naming both squares.

        The echo is the only check that what was heard is what was meant. "e
        four. Good." cannot catch a move that parsed to a different legal move
        than intended -- the robot's board is then internally consistent and
        simply wrong, which is the hardest kind of desync to trace.
        """
        self.body.attend(False)
        self.body.speak(
            phrases.pick(phrases.CONFIRM, move_number, move=spoken),
            pose="neutral",
        )

    def coach(self, judgement: Judgement, move_number: int) -> None:
        """Comment on the child's move.

        Only called when Coach.should_comment agreed, so the restraint decision
        has already been made upstream. This layer chooses only how it looks
        and sounds.
        """
        pose, gesture = JUDGEMENT_EXPRESSION.get(judgement.label, ("neutral", None))
        best = moves.say_move(judgement.best_san) if judgement.best_san else ""

        self.body.look_at("child")
        line = phrases.coaching(judgement.label, move_number, best=best)
        if line:
            self.body.speak(line, pose=pose, gesture=gesture)

        if judgement.missed_mate:
            self.body.speak(phrases.pick(phrases.MISSED_MATE, move_number), pose="concerned")

    def warn_check(self, move_number: int) -> None:
        self.body.speak(
            phrases.pick(phrases.CHECK_WARNING, move_number),
            pose="concerned",
            gesture="lean_in",
        )

    # -- thinking ------------------------------------------------------

    def thinking(self, on: bool = True) -> None:
        """Show that a decision is happening.

        Paired with a pose rather than relying on the eye LEDs, which need an
        accessory that may not be fitted. No state may ever be signalled by
        colour alone.
        """
        if on:
            self.body.attend(False)
            self.body.set_state("thinking")
            self.body.express("thinking")
            self.body.look_at("away")
        else:
            self.body.set_state("listening")
            self.body.express("neutral")
            self.body.look_at("child")

    # -- input problems ------------------------------------------------

    def illegal(self, parsed: moves.Parsed, board: chess.Board, move_number: int) -> None:
        reason = moves.explain_illegal(parsed, board)
        self.body.speak(
            phrases.pick(phrases.ILLEGAL, move_number, reason=reason),
            pose="concerned",
            gesture="tilt",
        )

    def ambiguous(self, parsed: moves.Parsed, board: chess.Board, move_number: int) -> None:
        """Ask which piece was meant.

        Distinct from 'not understood' on purpose. The child was perfectly
        clear; the position was ambiguous, and saying "I didn't catch that"
        blames the wrong party.

        The question names ORIGIN SQUARES, which is what a person looking at a
        board can actually see. Reading out disambiguated SAN ("knight from the
        b file") asks them to translate notation mid-game.
        """
        origins = [moves.say_square(chess.square_name(m.from_square)) for m in parsed.candidates]
        piece = board.piece_at(parsed.candidates[0].from_square)
        name = chess.piece_name(piece.piece_type) if piece else "piece"

        self.body.speak(
            phrases.pick(
                phrases.AMBIGUOUS,
                move_number,
                piece=name,
                options=phrases.join_options(origins),
            ),
            pose="neutral",
            gesture="tilt",
        )

    def not_understood(self, move_number: int) -> None:
        self.body.speak(
            phrases.pick(phrases.NOT_UNDERSTOOD, move_number),
            pose="neutral",
            gesture="double_blink",
        )

    def offer_keyboard(self) -> None:
        self.body.speak(phrases.pick(phrases.FALLBACK_TO_KEYBOARD), pose="neutral")

    def help(self) -> None:
        self.body.speak(phrases.pick(phrases.HELP), pose="neutral")

    # -- board recovery ------------------------------------------------

    def read_board(self, state: GameState) -> None:
        """Read the position aloud.

        With no camera this is the only recovery path when the physical board
        and the internal one have diverged, so it is in v1 rather than deferred.
        """
        self.body.look_at("board")
        self.body.speak(phrases.pick(phrases.BOARD_INTRO), pose="neutral")
        for line in state.describe_position():
            self.body.speak(_spoken_squares(line), pose="neutral")
        self.body.look_at("child")

    def undone(self, undone: list[str], move_number: int) -> None:
        """Say WHICH moves are being taken back.

        An undo pops two plies -- the person's move and the robot's reply --
        but "taking that back" names neither. Reverse only your own move on the
        physical board and you are out by one piece immediately, with nothing
        said on either side. Naming both makes the omission obvious.
        """
        if not undone:
            self.body.speak(phrases.pick(phrases.NOTHING_TO_UNDO, move_number), pose="neutral")
            return

        self.body.look_at("child")
        self.body.speak(
            phrases.pick(phrases.UNDO, move_number, moves=phrases.join_options(undone)),
            pose="neutral",
            gesture="nod",
        )

    # -- endings -------------------------------------------------------

    def game_over(self, state: GameState) -> None:
        result = state.result_for_child()
        self.body.look_at("child")

        if state.board.is_stalemate():
            self.body.speak(phrases.pick(phrases.STALEMATE), pose="neutral")
        elif result == "win":
            self.body.speak(phrases.pick(phrases.CHILD_WINS), pose="impressed", gesture="perk_up")
        elif result == "loss":
            self.body.speak(phrases.pick(phrases.ROBOT_WINS), pose="pleased", gesture="nod")
        else:
            self.body.speak(phrases.pick(phrases.DRAW), pose="neutral")

    def resigned(self) -> None:
        self.body.look_at("child")
        self.body.speak(phrases.pick(phrases.RESIGN), pose="pleased", gesture="nod")


def _spoken_squares(line: str) -> str:
    """Rewrite square names in a sentence so they are read aloud correctly.

    'rooks on a1 and h1' -> 'rooks on a one and h one'. Left as digits, a TTS
    engine reads "a1" as a word or spells it inconsistently.
    """
    out = []
    for token in line.split():
        stripped = token.strip(".,")
        trailing = token[len(stripped) :]
        if len(stripped) == 2 and stripped[0] in "abcdefgh" and stripped[1] in "12345678":
            out.append(moves.say_square(stripped) + trailing)
        else:
            out.append(token)
    return " ".join(out)
