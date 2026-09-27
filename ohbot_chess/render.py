# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Drawing the board in the terminal.

This is for the ADULT debugging a game, and is a different thing from the
spoken `board` readback, which is for a person who cannot see a screen. Both
exist; neither replaces the other.

Three decisions worth knowing about:

FILLED GLYPHS FOR BOTH COLOURS. The outline pieces (U+2654-2659) and the filled
ones (U+265A-265F) are drawn at noticeably different weights in most terminal
fonts, and on a coloured background the outline set can vanish completely.
Using the filled shapes for both sides and distinguishing by FOREGROUND colour
renders reliably everywhere.

AN ASCII MODE THAT IS NOT AN AFTERTHOUGHT. Chess glyphs are missing or
mis-spaced in plenty of terminal fonts, and a board you cannot read is
maddening when the board is the thing you are debugging.

COLOUR ONLY WHEN ATTACHED TO A TERMINAL. Piping to a file should give clean
text you can paste into a bug report without escape sequences through it.
"""

from __future__ import annotations

import sys
from collections.abc import Collection

import chess

# Filled glyphs for both sides -- see the module docstring.
GLYPHS = {
    chess.PAWN: "\u265f",
    chess.KNIGHT: "\u265e",
    chess.BISHOP: "\u265d",
    chess.ROOK: "\u265c",
    chess.QUEEN: "\u265b",
    chess.KING: "\u265a",
}

# Background 8-bit colours: light square, dark square, last move, highlight.
LIGHT = 180
DARK = 137
LAST = 108  # muted green: where the last move went
MARK = 179  # amber: candidate origins during a clarification

WHITE_PIECE = 231  # near-white
BLACK_PIECE = 232  # near-black

RESET = "\033[0m"


def supports_colour(stream: object | None = None) -> bool:
    """Whether to emit ANSI. False when piped, redirected, or NO_COLOR is set."""
    import os

    if os.environ.get("NO_COLOR"):
        return False
    handle = stream if stream is not None else sys.stdout
    return bool(getattr(handle, "isatty", lambda: False)())


def render(
    board: chess.Board,
    *,
    orientation: bool = chess.WHITE,
    last_move: chess.Move | None = None,
    highlight: Collection[int] = (),
    unicode: bool = True,
    colour: bool | None = None,
    coordinates: bool = True,
) -> str:
    """The board as printable text.

    `orientation` is whose side to view it from -- default White, so it matches
    what a person playing White sees in front of them. Handing someone a board
    drawn from the wrong side while they are trying to spot a discrepancy is a
    good way to manufacture one.
    """
    if colour is None:
        colour = supports_colour()

    marked = set(highlight)
    moved = {last_move.from_square, last_move.to_square} if last_move else set()

    ranks = range(7, -1, -1) if orientation == chess.WHITE else range(8)
    files = range(8) if orientation == chess.WHITE else range(7, -1, -1)

    lines = []
    for rank in ranks:
        cells = []
        for file in files:
            square = chess.square(file, rank)
            cells.append(_cell(board, square, square in moved, square in marked, unicode, colour))
        label = f"{rank + 1} " if coordinates else ""
        lines.append(label + "".join(cells))

    if coordinates:
        letters = "  " + "".join(f" {chess.FILE_NAMES[f]} " for f in files)
        lines.append(letters)

    return "\n".join(lines)


def _cell(
    board: chess.Board,
    square: int,
    is_last: bool,
    is_marked: bool,
    unicode: bool,
    colour: bool,
) -> str:
    piece = board.piece_at(square)

    if unicode:
        symbol = GLYPHS[piece.piece_type] if piece else " "
    else:
        # Standard ASCII convention: uppercase White, lowercase Black.
        symbol = piece.symbol() if piece else "."

    if not colour:
        # Without colour, filled glyphs cannot show which side a piece is on,
        # so fall back to the letter convention regardless of `unicode`.
        if piece is not None:
            symbol = piece.symbol()
        return f" {symbol} "

    if is_marked:
        background = MARK
    elif is_last:
        background = LAST
    else:
        light = (chess.square_file(square) + chess.square_rank(square)) % 2 == 1
        background = LIGHT if light else DARK

    if piece is None:
        return f"\033[48;5;{background}m   {RESET}"

    foreground = WHITE_PIECE if piece.color == chess.WHITE else BLACK_PIECE
    return f"\033[48;5;{background}m\033[38;5;{foreground}m {symbol} {RESET}"


# -- surrounding information ------------------------------------------------

VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}


def material(board: chess.Board) -> int:
    """Material balance in pawns, positive meaning White is ahead."""
    total = 0
    for piece_type, value in VALUES.items():
        total += value * len(board.pieces(piece_type, chess.WHITE))
        total -= value * len(board.pieces(piece_type, chess.BLACK))
    return total


def status_line(board: chess.Board, child_colour: bool = chess.WHITE) -> str:
    """Whose turn, castling rights, material -- the things an edit can break.

    Castling rights are shown because they cannot be inferred from where the
    pieces are: a king and rook on their home squares says nothing about
    whether either has moved. After a position edit that is exactly the
    invisible state most likely to be wrong.
    """
    turn = "White" if board.turn == chess.WHITE else "Black"
    whose = "you" if board.turn == child_colour else "Ohbot"

    balance = material(board)
    if balance == 0:
        standing = "material level"
    else:
        ahead = "White" if balance > 0 else "Black"
        standing = f"{ahead} up {abs(balance)}"

    # Read from the FEN field rather than castling_xfen(), which is only
    # unambiguous for standard chess and returns a different shape for 960.
    rights = board.fen().split()[2]
    extras = [f"castling {rights}"]
    if board.ep_square is not None:
        extras.append(f"en passant {chess.square_name(board.ep_square)}")
    if board.is_check():
        extras.append("CHECK")

    return f"{turn} to move ({whose}) | {standing} | " + " | ".join(extras)


def show(
    board: chess.Board,
    *,
    orientation: bool = chess.WHITE,
    last_move: chess.Move | None = None,
    highlight: Collection[int] = (),
    unicode: bool = True,
    child_colour: bool = chess.WHITE,
    note: str = "",
) -> str:
    """Board, status line and FEN together -- what you paste into a bug report."""
    parts = [
        render(
            board,
            orientation=orientation,
            last_move=last_move,
            highlight=highlight,
            unicode=unicode,
        ),
        status_line(board, child_colour),
        board.fen(),
    ]
    if note:
        parts.insert(0, note)
    return "\n".join(parts)
