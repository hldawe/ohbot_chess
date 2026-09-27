# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The turn loop.

The shape of a turn is set by the one constraint that defines this whole
application: the robot cannot reach the board. So its own move is not something
it makes, it is something it ASKS FOR, and the loop has to wait for hands that
are not its own.

That waiting is the part most easily got wrong, and it was got wrong on the
previous build: the robot asked "have you moved it?" while a hand was still
over the board. Patience here is a feature with a number attached
(config.PATIENCE_SECONDS), not a vague intention.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Protocol

import chess

from . import config, moves, phrases, render
from . import listener as listener_mod
from .chess_core import Coach, Engine, GameState
from .presentation import Presenter

# How a wait for the physical board ended.
DONE = "done"  # the piece was moved
REJECTED = "rejected"  # it cannot be played -- withdraw and try another
UNDONE = "undone"  # take back this move and the one before it
STOPPED = "stopped"  # the game is over


# -- input ------------------------------------------------------------------


class Input(Protocol):
    """Where the child's words come from.

    `blocking` says what an empty return MEANS, and the two cases are opposite.
    A typed empty line is someone pressing Enter to say "done". An empty return
    from a microphone is a timeout -- silence while a hand is busy on the board.
    Treating those the same either ignores the keyboard or nudges constantly.
    """

    blocking: bool

    def get(self, phrases_allowed: list[str], body: Any = None) -> str: ...
    def close(self) -> None: ...


class KeyboardInput:
    """Typed input. Always available, and always the fallback."""

    blocking = True

    def __init__(self, prompt: str = "> ") -> None:
        self.prompt = prompt

    def get(self, phrases_allowed: list[str], body: Any = None) -> str:
        try:
            return input(self.prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return "stop"

    def close(self) -> None:
        pass


class VoiceInput:
    """Spoken input via Vosk, with the keyboard behind it.

    Falls back after repeated failures rather than looping forever. Being stuck
    with a robot that cannot hear you and will not let you type is worse than
    any recognition error.
    """

    blocking = False

    def __init__(self, listener: Any, fallback: Input | None = None, patience: int = 3) -> None:
        self.listener = listener
        self.fallback = fallback or KeyboardInput()
        self.patience = patience
        self._failures = 0

    def get(self, phrases_allowed: list[str], body: Any = None) -> str:
        if self._failures >= self.patience:
            return self.fallback.get(phrases_allowed, body)

        grammar = listener_mod.build_grammar(phrases_allowed)
        try:
            text = self.listener.listen(grammar, body=body)
        except Exception as e:
            print(f"[voice] {e}", file=sys.stderr)
            self._failures = self.patience
            return self.fallback.get(phrases_allowed, body)

        if text:
            self._failures = 0
        else:
            self._failures += 1
        return text

    def close(self) -> None:
        self.fallback.close()


class ScriptedInput:
    """A fixed list of utterances. Lets the whole loop run in a test."""

    blocking = True

    def __init__(self, script: list[str], blocking: bool = True) -> None:
        self.blocking = blocking
        self.script = list(script)
        self.asked: list[list[str]] = []

    def get(self, phrases_allowed: list[str], body: Any = None) -> str:
        self.asked.append(list(phrases_allowed))
        if not self.script:
            return "stop"
        return self.script.pop(0)

    def close(self) -> None:
        pass


# -- the game ---------------------------------------------------------------


class Game:
    """One game of chess between a robot with no hands and a person with two."""

    def __init__(
        self,
        state: GameState,
        engine: Engine,
        presenter: Presenter,
        source: Input,
        coach: Coach | None = None,
        teach: bool = True,
        patience: float = config.PATIENCE_SECONDS,
        sleep: Any = time.sleep,
        journal: Any = None,
        screen: Any = None,
        editor: Any = None,
    ) -> None:
        self.state = state
        self.engine = engine
        self.presenter = presenter
        self.source = source
        self.coach = coach
        self.teach = teach and coach is not None
        self.patience = patience
        self._sleep = sleep  # injectable so tests don't wait in real time
        self.journal = journal
        self.screen = screen  # prints the board; None disables it
        self.editor = editor  # opens the position editor; None disables it
        self.stopped = False
        self.resigned = False
        self._last_robot_san: str | None = None
        self._last_robot_spoken: str | None = None
        # Candidates from an unanswered "which piece?" question. Holding them
        # means a bare origin square answers it, instead of the whole move
        # having to be said again.
        self._pending: list[chess.Move] = []

    # -- output --------------------------------------------------------

    def draw(self, note: str = "", highlight: Any = ()) -> None:
        """Print the board, if a screen was given."""
        if self.screen is None:
            return
        last = self.state.board.move_stack[-1] if self.state.board.move_stack else None
        self.screen(
            render.show(
                self.state.board,
                orientation=self.state.child_colour,
                last_move=last,
                highlight=highlight,
                child_colour=self.state.child_colour,
                note=note,
            )
        )

    def _log(self, method: str, *args: Any, **kwargs: Any) -> None:
        if self.journal is not None:
            getattr(self.journal, method)(*args, **kwargs)

    def _save(self, result: str = "*") -> None:
        if self.journal is not None:
            self.journal.write_pgn(self.state.board, result)

    # -- driver --------------------------------------------------------

    def play(self) -> str:
        """Play until the game ends or is stopped. Returns the result."""
        self.presenter.greet(self.state)
        self.draw()

        while not self.state.is_over and not self.stopped:
            if self.state.robot_to_move:
                self.robot_turn()
            else:
                self.child_turn()

        if self.resigned:
            self.presenter.resigned()
        elif self.state.is_over:
            self.presenter.game_over(self.state)
        self.presenter.farewell()

        result = self.state.result_for_child()
        outcome = self.state.board.result() if self.state.is_over else "*"
        self._log("finish", result, self.state.fen)
        self._save(outcome)
        return result

    # -- the robot's turn ----------------------------------------------

    def robot_turn(self) -> None:
        """Choose a move, announce it, and wait for someone else's hands.

        The robot can ask for a move that cannot be played on the physical
        board -- not because the engine produced an illegal move, but because
        the two boards have drifted apart, and its move is legal only in the
        position it thinks it is in. With no camera it cannot discover this by
        itself, so the person has to be able to say so, and the robot has to
        be able to withdraw the move and try a different one.

        Rejected moves accumulate, so it never offers the same one twice.
        """
        rejected: set[chess.Move] = set()

        while not self.stopped:
            self.presenter.thinking(True)
            move = self.engine.choose(self.state, exclude=rejected)
            self.presenter.thinking(False)

            if move is None:
                # Everything it can think of has been refused, which means the
                # two boards disagree about more than one piece. Guessing
                # again would waste everyone's time.
                #
                # This branch MUST change the game state. Returning here left
                # it still the robot's turn, so play() called straight back in
                # and the game span forever without printing anything new.
                # Taking a move pair back guarantees progress -- the stack can
                # only shrink -- and hands the turn to the person, which is
                # what recovery actually needs.
                self.presenter.out_of_ideas()
                self.presenter.read_board(self.state)
                if self.state.undo_pair() == 0:
                    self.stopped = True  # nothing left to take back
                elif self.coach is not None:
                    self.coach.reset()
                return

            san = self.state.san(move)
            spoken = moves.narrate(move, self.state.board)
            self.presenter.announce(self.state, move, san)
            self._last_robot_san = san
            self._last_robot_spoken = spoken
            self.state.push(move)
            self._log("move", "ohbot", san, move.uci(), self.state.fen, spoken=spoken)
            self._save()
            self.draw()

            outcome = self.wait_for_hands(san, spoken)

            if outcome == REJECTED:
                before = self.state.fen
                self.state.board.pop()  # withdraw it; it was never played
                rejected.add(move)
                self._log("correction", "move refused", before, self.state.fen, san=san)
                self.presenter.try_another(self.state.move_number)
                continue

            if outcome == UNDONE:
                # Take back this move AND the one before it, so it is the
                # person's turn again and they can replay from a position both
                # sides agree on.
                self._undo(reason="undo while waiting")
            return

    def wait_for_hands(self, san: str, spoken: str = "") -> str:
        """Wait for the piece to be physically moved.

        Returns DONE, REJECTED, UNDONE or STOPPED.

        Nudges are spaced and never immediate. The person is reaching across a
        board and finding a square; the robot has nothing else to do and no
        reason at all to hurry them.

        `again` re-announces the move, because the most common reason for a
        pause is having forgotten what was asked for.
        """
        allowed = list(listener_mod.CONTROL_WORDS)
        deadline = time.time() + self.patience

        while not self.stopped:
            reply = self.source.get(allowed, self.presenter.body)
            command = listener_mod.control_word(reply) if reply else None

            if command == "done":
                return DONE
            if command == "cannot":
                return REJECTED
            if command == "undo":
                return UNDONE
            if command == "repeat":
                self.presenter.repeat_move(spoken or san, self.state.move_number)
                deadline = time.time() + self.patience
                continue
            if command in ("stop", "resign"):
                self._handle_control(command)
                return STOPPED
            if command == "board":
                self.presenter.read_board(self.state)
                continue
            if command in ("show", "fix", "correct"):
                # Most likely to be wanted at exactly this moment: being asked
                # to move a piece that is not where the robot thinks it is.
                self._handle_control(command)
                continue
            if command == "help":
                self.presenter.help()
                continue
            if reply.strip() == "":
                if getattr(self.source, "blocking", True):
                    return DONE  # a typed empty line is "done"
                # Silence from a microphone is normal -- a hand is busy. Only
                # nudge once the patience window has actually elapsed.
                if time.time() >= deadline:
                    self.presenter.nudge(self.state.move_number)
                    deadline = time.time() + config.NUDGE_INTERVAL_SECONDS
                self._sleep(0.2)
                continue

            # Unrecognised words used to be taken as "yes, done". That quietly
            # swallowed every protest: told its move was impossible, the robot
            # heard confirmation and played on. Say what was not understood
            # instead, and keep waiting.
            self.presenter.not_understood_while_waiting(self.state.move_number)

        return STOPPED

    # -- the child's turn ----------------------------------------------

    def child_turn(self) -> None:
        self.presenter.invite(self.state.move_number)

        while not self.stopped:
            allowed = self._grammar_phrases()
            reply = self.source.get(allowed, self.presenter.body)

            # An outstanding "which piece?" is answered by a bare origin
            # square. Sending that through the full parser instead would
            # resolve nothing and force the whole move to be repeated.
            if self._pending:
                chosen = moves.resolve_clarification(reply, self._pending, self.state.board)
                if chosen is not None:
                    self._log("heard", "child", reply, "clarification", chosen.uci())
                    self._pending = []
                    self._accept(chosen)
                    return

            command = listener_mod.control_word(reply) if reply else None
            if command and self._handle_control(command):
                # An undo with only one ply on the stack hands the turn to the
                # other player, so the loop has to re-check whose turn it is
                # rather than assuming it is still the child's.
                if self.stopped or not self.state.child_to_move:
                    return
                continue

            if not reply.strip():
                self.presenter.not_understood(self.state.move_number)
                continue

            parsed = moves.parse(reply, self.state.board)
            self._log(
                "heard",
                "child",
                reply,
                parsed.kind,
                parsed.move.uci() if parsed.move else None,
                normalised=parsed.normalised,
            )

            if parsed.kind == moves.AMBIGUOUS:
                # Remember what was offered, and show the candidate origins on
                # the board so the question is answerable at a glance.
                self._pending = list(parsed.candidates)
                self.presenter.ambiguous(parsed, self.state.board, self.state.move_number)
                self.draw(
                    note="Which one?",
                    highlight=[m.from_square for m in parsed.candidates],
                )
                continue
            if parsed.kind == moves.ILLEGAL:
                self.presenter.illegal(parsed, self.state.board, self.state.move_number)
                continue
            if parsed.kind == moves.UNKNOWN or parsed.move is None:
                self.presenter.not_understood(self.state.move_number)
                continue

            self._pending = []
            self._accept(parsed.move)
            return

    def _accept(self, move: chess.Move) -> None:
        """Play the child's move, judging it first.

        Judging happens BEFORE the move is played, because the coach needs the
        position the decision was made in. Judge is non-mutating.
        """
        judgement = None
        if self.teach and self.coach is not None:
            judgement = self.coach.judge(self.state, move)

        spoken = moves.narrate(move, self.state.board)
        san = self.state.push(move)
        self.presenter.confirm(spoken, self.state.move_number)
        self._log("move", "child", san, move.uci(), self.state.fen, spoken=spoken)
        self._save()
        self.draw()

        if (
            judgement is not None
            and self.coach is not None
            and self.coach.should_comment(judgement, self.state.move_number)
        ):
            self.presenter.coach(judgement, self.state.move_number)

    # -- control commands ----------------------------------------------

    def _handle_control(self, command: str) -> bool:
        """Deal with a control word. Returns True if it was handled here."""
        if command == "stop":
            self.stopped = True
            return True
        if command == "resign":
            self.stopped = True
            self.resigned = True
            return True
        if command == "board":
            self.presenter.read_board(self.state)
            return True
        if command == "show":
            self.draw()
            return True
        if command in ("fix", "correct"):
            self.correct_position()
            return True
        if command == "help":
            self.presenter.help()
            return True
        if command == "cannot":
            # Said on the person's own turn, this is about the robot's LAST
            # move -- they have gone to move the piece, found they can't, and
            # come back to it. Too late to withdraw cleanly, so take the pair
            # back and let them replay from a position both sides agree on.
            plies = self.state.undo_pair()
            self.presenter.rewind_after_refusal(plies, self.state.move_number)
            if self.coach is not None:
                self.coach.reset()
            return True
        if command == "undo":
            self._undo(reason="undo requested")
            return True
        if command == "repeat":
            if self._last_robot_spoken:
                self.presenter.repeat_move(self._last_robot_spoken, self.state.move_number)
            return True
        return command == "done"

    def correct_position(self) -> bool:
        """Hand the board to the position editor.

        The robot cannot see the pieces, so when the two boards disagree the
        only source of truth is the person looking at the real one.
        """
        if self.editor is None:
            self.draw(note="Position editing is not available in this session.")
            return False

        before = self.state.fen
        corrected = self.editor(self.state.board, self.state.child_colour)
        if corrected is None:
            return False

        self.state.board = corrected
        if self.coach is not None:
            self.coach.reset()
        self._log("correction", "position edited", before, self.state.fen)
        self._save()
        self.draw(note="Corrected.")
        return True

    def _undo(self, reason: str = "undo") -> int:
        """Take back a move pair, naming both moves out loud.

        Reading the SAN off BEFORE popping is the only way to name them: once
        the moves are off the stack the position no longer supports generating
        their notation.
        """
        before = self.state.fen
        board = self.state.board

        names: list[str] = []
        replay = board.copy()
        for _ in range(min(2, len(replay.move_stack))):
            move = replay.pop()
            names.append(moves.narrate(move, replay))
        names.reverse()

        plies = self.state.undo_pair()
        self.presenter.undone(names, self.state.move_number)
        if plies and self.coach is not None:
            self.coach.reset()
        self._log("correction", reason, before, self.state.fen, undone=names)
        self._save()
        self.draw()
        return plies

    # -- grammar -------------------------------------------------------

    def _grammar_phrases(self) -> list[str]:
        """Every phrasing of every legal move, for this turn only.

        This is what makes the recogniser unable to return an illegal move. It
        has to be rebuilt each turn -- a stale grammar is worse than none,
        because it is confidently wrong.
        """
        out: list[str] = []
        for move in self.state.legal_moves():
            out.extend(moves.spoken_forms(move, self.state.board))
        return out


def describe_result(state: GameState) -> str:
    """A short line for the terminal, distinct from anything spoken."""
    result = state.result_for_child()
    return {
        "win": "You won.",
        "loss": "Ohbot won.",
        "draw": "A draw.",
        "unfinished": "Game stopped.",
    }[result]


__all__ = [
    "DONE",
    "REJECTED",
    "UNDONE",
    "STOPPED",
    "Game",
    "Input",
    "KeyboardInput",
    "VoiceInput",
    "ScriptedInput",
    "describe_result",
    "phrases",
]
