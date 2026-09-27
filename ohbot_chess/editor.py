# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Correcting the robot's idea of where the pieces are.

The robot cannot see the board. When the two drift apart there has to be a way
to tell it the truth, and reading a whole position aloud is not it -- that is
for a child with no screen. This is for whoever is debugging.

FOUR THINGS THIS GETS RIGHT, BECAUSE EACH IS EASY TO GET WRONG

1. EDITING DESTROYS THE UNDO HISTORY. Once a position is set directly, the
   move stack no longer leads to it, so `take that back` cannot reach past the
   edit. python-chess clears the stack on a FEN load and there is no honest way
   around that. So the editor says so, out loud, on the way out -- rather than
   leaving someone with an undo that silently does nothing.

2. CASTLING RIGHTS CANNOT BE INFERRED FROM PIECE PLACEMENT. A king and rook on
   their home squares says nothing about whether either has moved. They are
   carried over from the position being replaced where that is still possible,
   shown in the status line, and settable directly.

3. WHOSE TURN IT IS BECOMES AMBIGUOUS after an edit, and getting it wrong
   desyncs you again immediately. It is always shown and always settable.

4. THE RESULT IS VALIDATED BEFORE PLAY RESUMES. python-chess knows about two
   kings, pawns on the back rank, the side not to move standing in check. An
   editor that lets you resume from an impossible position is worse than no
   editor, because the engine's behaviour then makes no sense either.
"""

from __future__ import annotations

from collections.abc import Callable

import chess

from . import render

PIECE_WORDS = {
    "k": chess.KING,
    "king": chess.KING,
    "q": chess.QUEEN,
    "queen": chess.QUEEN,
    "r": chess.ROOK,
    "rook": chess.ROOK,
    "castle": chess.ROOK,
    "b": chess.BISHOP,
    "bishop": chess.BISHOP,
    "n": chess.KNIGHT,
    "knight": chess.KNIGHT,
    "horse": chess.KNIGHT,
    "p": chess.PAWN,
    "pawn": chess.PAWN,
}

COLOUR_WORDS = {
    "w": chess.WHITE,
    "white": chess.WHITE,
    "b": chess.BLACK,
    "black": chess.BLACK,
}

HELP = """
  set e4 white knight     put a piece on a square  (also: set e4 wn)
  clear e4                take a piece off
  move e4 f6              relocate a piece, no legality check
  turn white              whose move it is
  castling KQkq           set rights directly ('-' for none)
  fen <string>            replace the whole position
  reset                   back to the starting position
  show                    redraw
  undo                    step back through your edits
  done                    finish and resume
  cancel                  discard every edit
"""

# What python-chess's status flags mean, in words that suggest a fix.
STATUS_MESSAGES = [
    (chess.STATUS_NO_WHITE_KING, "there is no white king"),
    (chess.STATUS_NO_BLACK_KING, "there is no black king"),
    (chess.STATUS_TOO_MANY_KINGS, "there is more than one king of a colour"),
    (chess.STATUS_TOO_MANY_WHITE_PAWNS, "white has more than eight pawns"),
    (chess.STATUS_TOO_MANY_BLACK_PAWNS, "black has more than eight pawns"),
    (chess.STATUS_PAWNS_ON_BACKRANK, "a pawn is on the first or eighth rank"),
    (chess.STATUS_TOO_MANY_WHITE_PIECES, "white has too many pieces"),
    (chess.STATUS_TOO_MANY_BLACK_PIECES, "black has too many pieces"),
    (
        chess.STATUS_BAD_CASTLING_RIGHTS,
        "the castling rights don't match where the kings and rooks are",
    ),
    (chess.STATUS_INVALID_EP_SQUARE, "the en passant square is impossible"),
    (
        chess.STATUS_OPPOSITE_CHECK,
        "the player who is NOT to move is in check, which cannot happen",
    ),
    (chess.STATUS_IMPOSSIBLE_CHECK, "the checks in this position cannot both be true"),
]


def problems(board: chess.Board) -> list[str]:
    """Plain-English reasons a position could not occur in a real game."""
    status = board.status()
    return [message for flag, message in STATUS_MESSAGES if status & flag]


class PositionEditor:
    """A small command loop over a working copy of the board.

    Works on a copy, so `cancel` genuinely discards and a validation failure
    never leaves a half-edited position in play.
    """

    def __init__(
        self,
        board: chess.Board,
        orientation: bool = chess.WHITE,
        unicode: bool = True,
        write: Callable[[str], None] = print,
        ask: Callable[[str], str] = input,
    ) -> None:
        self.original = board.copy()
        self.board = board.copy()
        self.orientation = orientation
        self.unicode = unicode
        self.write = write
        self.ask = ask
        self.history: list[str] = []
        self.edited = False

    # -- the loop ------------------------------------------------------

    def run(self) -> chess.Board | None:
        """Edit until done or cancelled.

        Returns the new board, or None if nothing should change.
        """
        self.write("\nPosition editor. Type help for commands, done when finished.")
        self.show()

        while True:
            try:
                line = self.ask("edit> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.write("\nCancelled. Nothing changed.")
                return None

            if not line:
                continue

            command, _, rest = line.partition(" ")
            command = command.lower()
            rest = rest.strip()

            if command in ("done", "ok", "finish"):
                if self.finish():
                    return self.board
                continue
            if command in ("cancel", "abort", "quit"):
                self.write("Cancelled. Nothing changed.")
                return None
            if command in ("help", "?"):
                self.write(HELP)
                continue
            if command == "show":
                self.show()
                continue
            if command == "undo":
                self.undo()
                continue

            handler = {
                "set": self.set_piece,
                "put": self.set_piece,
                "clear": self.clear_square,
                "remove": self.clear_square,
                "move": self.move_piece,
                "turn": self.set_turn,
                "castling": self.set_castling,
                "fen": self.set_fen,
                "reset": lambda _: self.reset(),
            }.get(command)

            if handler is None:
                self.write(f"Don't know '{command}'. Type help.")
                continue

            before = self.board.fen()
            try:
                handler(rest)
            except ValueError as e:
                self.write(f"  {e}")
                continue

            if command != "fen":
                # An en passant square records that a specific pawn moved two
                # squares on the previous move. Move or remove any piece and
                # that claim no longer holds, so the square has to go -- and
                # since python-chess validates it, a stale one makes the whole
                # position illegal and blocks the edit for a reason nobody
                # would guess from the message.
                self.board.ep_square = None
            if self.board.fen() != before:
                self.history.append(before)
                self.edited = True
                self.show()

    # -- commands ------------------------------------------------------

    def set_piece(self, rest: str) -> None:
        parts = rest.split()
        if len(parts) < 2:
            raise ValueError("usage: set e4 white knight   (or: set e4 wn)")

        square = _square(parts[0])
        piece = _piece(parts[1:])
        self.board.set_piece_at(square, piece)

    def clear_square(self, rest: str) -> None:
        if not rest:
            raise ValueError("usage: clear e4")
        for token in rest.split():
            self.board.remove_piece_at(_square(token))

    def move_piece(self, rest: str) -> None:
        """Relocate without legality checks.

        Deliberately not a move: the whole reason for being here is that the
        position is wrong, so refusing an 'illegal' correction would be
        precisely backwards.
        """
        parts = rest.split()
        if len(parts) != 2:
            raise ValueError("usage: move e4 f6")
        origin, target = _square(parts[0]), _square(parts[1])
        piece = self.board.piece_at(origin)
        if piece is None:
            raise ValueError(f"there is nothing on {parts[0]}")
        self.board.remove_piece_at(origin)
        self.board.set_piece_at(target, piece)

    def set_turn(self, rest: str) -> None:
        key = rest.strip().lower()
        if key not in COLOUR_WORDS:
            raise ValueError("usage: turn white   (or: turn black)")
        self.board.turn = COLOUR_WORDS[key]

    def set_castling(self, rest: str) -> None:
        text = rest.strip() or "-"
        try:
            self.board.set_castling_fen(text)
        except ValueError as e:
            raise ValueError(f"castling rights must look like KQkq or -: {e}") from None

    def set_fen(self, rest: str) -> None:
        if not rest:
            raise ValueError("usage: fen <position>")
        try:
            self.board.set_fen(rest)
        except ValueError as e:
            raise ValueError(f"that isn't a valid FEN: {e}") from None

    def reset(self) -> None:
        self.board.reset()

    def undo(self) -> None:
        if not self.history:
            self.write("  Nothing to undo.")
            return
        self.board.set_fen(self.history.pop())
        self.edited = bool(self.history)
        self.show()

    # -- finishing -----------------------------------------------------

    def finish(self) -> bool:
        """Validate and confirm. Returns True if the edit should be applied."""
        found = problems(self.board)
        if found:
            self.write("\n  This position can't happen in a real game:")
            for problem in found:
                self.write(f"    - {problem}")
            self.write("  Fix it, or type cancel to discard.\n")
            return False

        if not self.edited:
            self.write("No changes made.")
            return True

        # The one consequence that is invisible and cannot be undone later.
        if self.original.move_stack:
            self.write(
                "\n  Note: the move history is cleared by an edit, so 'take that\n"
                "  back' won't reach past this point."
            )
        self.write("  Position updated.\n")
        return True

    # -- display -------------------------------------------------------

    def show(self) -> None:
        self.write("")
        self.write(render.render(self.board, orientation=self.orientation, unicode=self.unicode))
        self.write(render.status_line(self.board))
        found = problems(self.board)
        if found:
            self.write("  (not yet a legal position: " + "; ".join(found) + ")")


# -- parsing ----------------------------------------------------------------


def _square(token: str) -> int:
    name = token.strip().lower()
    try:
        return chess.parse_square(name)
    except ValueError:
        raise ValueError(f"'{token}' isn't a square like e4") from None


def _piece(tokens: list[str]) -> chess.Piece:
    """Accept 'white knight', 'w n', 'wn', 'N' -- all the obvious spellings."""
    joined = " ".join(tokens).strip().lower()

    # Single FEN letter: N, n, Q, q...
    original = " ".join(tokens).strip()
    if len(original) == 1 and original.lower() in PIECE_WORDS:
        return chess.Piece(PIECE_WORDS[original.lower()], original.isupper())

    # Two-letter shorthand: wn, bq
    if len(joined) == 2 and joined[0] in COLOUR_WORDS and joined[1] in PIECE_WORDS:
        return chess.Piece(PIECE_WORDS[joined[1]], COLOUR_WORDS[joined[0]])

    words = joined.split()
    if len(words) == 2 and words[0] in COLOUR_WORDS and words[1] in PIECE_WORDS:
        return chess.Piece(PIECE_WORDS[words[1]], COLOUR_WORDS[words[0]])

    raise ValueError("say which piece, like 'white knight', 'wn', or 'N' for a white knight")
