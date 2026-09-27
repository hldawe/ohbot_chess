# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The debugging tools: drawing the board, correcting it, and logging a game."""

from __future__ import annotations

import json
from typing import Any

import chess
import pytest

from ohbot_chess import render
from ohbot_chess.editor import PositionEditor, problems
from ohbot_chess.journal import Journal

SPARSE = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"


def drive(fen: str, commands: list[str]) -> tuple[chess.Board | None, list[str]]:
    """Run the editor over a scripted session."""
    output: list[str] = []
    script = iter(commands)
    editor = PositionEditor(
        chess.Board(fen),
        write=lambda text: output.append(str(text)),
        ask=lambda _: next(script, "cancel"),
    )
    return editor.run(), output


# -- rendering --------------------------------------------------------------


def test_board_is_drawn_from_the_players_side() -> None:
    """Handing someone a board drawn from the wrong side while they are trying
    to spot a discrepancy is a good way to manufacture one."""
    board = chess.Board()
    white_view = render.render(board, orientation=chess.WHITE, colour=False)
    black_view = render.render(board, orientation=chess.BLACK, colour=False)

    assert white_view.splitlines()[0].startswith("8")
    assert black_view.splitlines()[0].startswith("1")
    assert white_view != black_view


def test_coordinates_mirror_with_the_board() -> None:
    board = chess.Board()
    black_view = render.render(board, orientation=chess.BLACK, colour=False)
    files = black_view.splitlines()[-1].split()
    assert files == list("hgfedcba")


def test_piped_output_has_no_escape_sequences() -> None:
    """Piping to a file should give text you can paste into a bug report."""
    drawn = render.render(chess.Board(), colour=False)
    assert "\033" not in drawn


def test_without_colour_pieces_are_still_distinguishable() -> None:
    """Filled glyphs carry colour in the foreground, so with colour stripped
    they would all look like Black. Fall back to letters instead."""
    drawn = render.render(chess.Board(), colour=False, unicode=True)
    assert "R" in drawn and "r" in drawn


def test_ascii_mode_uses_the_standard_convention() -> None:
    drawn = render.render(chess.Board(), unicode=False, colour=False)
    assert "P" in drawn  # white
    assert "p" in drawn  # black


def test_last_move_is_highlighted_when_colour_is_on() -> None:
    board = chess.Board()
    board.push_san("e4")
    plain = render.render(board, colour=True)
    marked = render.render(board, last_move=board.move_stack[-1], colour=True)
    assert plain != marked
    assert f"48;5;{render.LAST}" in marked


def test_material_balance() -> None:
    assert render.material(chess.Board()) == 0
    assert render.material(chess.Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")) == 9
    assert render.material(chess.Board("3qk3/8/8/8/8/8/8/4K3 w - - 0 1")) == -9


def test_status_line_shows_what_an_edit_can_break() -> None:
    """Castling rights and the side to move cannot be read off the pieces, and
    are exactly what a position edit gets wrong."""
    line = render.status_line(chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w Kq - 0 1"))
    assert "White to move" in line
    assert "Kq" in line


def test_status_line_flags_check() -> None:
    board = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    assert "CHECK" in render.status_line(board)


def test_show_includes_the_fen_for_pasting() -> None:
    text = render.show(chess.Board(), unicode=False)
    assert chess.STARTING_FEN in text


# -- the editor -------------------------------------------------------------


def test_pieces_can_be_placed_and_removed() -> None:
    board, _ = drive(SPARSE, ["set a3 white knight", "done"])
    assert board is not None
    assert board.piece_at(chess.A3) == chess.Piece(chess.KNIGHT, chess.WHITE)


@pytest.mark.parametrize("spelling", ["white knight", "wn", "w n", "N"])
def test_piece_spellings(spelling: str) -> None:
    board, _ = drive(SPARSE, [f"set a3 {spelling}", "done"])
    assert board is not None
    assert board.piece_at(chess.A3) == chess.Piece(chess.KNIGHT, chess.WHITE)


def test_move_ignores_legality() -> None:
    """The whole reason for being here is that the position is wrong, so
    refusing an 'illegal' correction would be precisely backwards."""
    board, _ = drive(SPARSE, ["move e1 e5", "done"])
    assert board is not None
    assert board.piece_at(chess.E5) == chess.Piece(chess.KING, chess.WHITE)
    assert board.piece_at(chess.E1) is None


def test_turn_can_be_set() -> None:
    """After an edit whose turn it is becomes ambiguous, and getting it wrong
    desyncs you again immediately."""
    board, _ = drive(SPARSE, ["turn black", "done"])
    assert board is not None
    assert board.turn == chess.BLACK


def test_castling_rights_can_be_set_directly() -> None:
    """They cannot be inferred: a king and rook on their home squares says
    nothing about whether either has moved."""
    board, _ = drive("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", ["castling Kq", "done"])
    assert board is not None
    assert board.fen().split()[2] == "Kq"


def test_cancel_discards_everything() -> None:
    board, _ = drive(SPARSE, ["set a3 wq", "set h6 bn", "cancel"])
    assert board is None


def test_undo_steps_back_through_edits() -> None:
    board, _ = drive(SPARSE, ["set a3 wq", "undo", "done"])
    assert board is not None
    assert board.piece_at(chess.A3) is None


def test_invalid_position_is_refused_with_a_reason() -> None:
    """An editor that lets you resume from an impossible position is worse than
    no editor, because the engine's behaviour then makes no sense either."""
    board, output = drive(SPARSE, ["clear e1", "done", "cancel"])
    assert board is None
    assert any("no white king" in line for line in output)


def test_stale_en_passant_does_not_block_an_edit() -> None:
    """An en passant square records that a specific pawn just moved two
    squares. Move or remove anything and that claim no longer holds -- and
    python-chess then rejects the whole position for a reason nobody would
    guess from the message."""
    board = chess.Board()
    board.push_san("e4")
    board.push_san("e5")
    assert board.ep_square is not None

    output: list[str] = []
    script = iter(["clear e5", "done"])
    editor = PositionEditor(
        board, write=lambda t: output.append(str(t)), ask=lambda _: next(script, "cancel")
    )
    result = editor.run()
    assert result is not None, "a valid edit was refused over a stale ep square"


def test_editing_warns_that_undo_history_goes() -> None:
    """The one consequence that is invisible and cannot be undone later."""
    board = chess.Board()
    board.push_san("e4")
    output: list[str] = []
    script = iter(["clear a7", "done"])  # removing a piece is always valid
    PositionEditor(
        board, write=lambda t: output.append(str(t)), ask=lambda _: next(script, "cancel")
    ).run()
    assert any("take that" in line for line in output)


def test_problem_messages_are_in_plain_english() -> None:
    found = problems(chess.Board("4k3/8/8/8/8/8/8/3KK3 w - - 0 1"))
    assert found
    assert all(not message[0].isupper() or " " in message for message in found)


def test_unknown_command_does_not_crash() -> None:
    board, output = drive(SPARSE, ["wibble", "done"])
    assert board is not None
    assert any("Don't know" in line for line in output)


# -- the journal ------------------------------------------------------------


def test_journal_writes_events_and_pgn(tmp_path: Any) -> None:
    journal = Journal(directory=tmp_path, name="test")
    journal.start(level="cub")

    board = chess.Board()
    journal.heard("child", "e four", "move", "e2e4")
    board.push_san("e4")
    journal.move("child", "e4", "e2e4", board.fen())
    journal.write_pgn(board)

    lines = [json.loads(line) for line in journal.events.read_text().splitlines()]
    assert [entry["kind"] for entry in lines] == ["start", "input", "move"]
    assert lines[1]["raw"] == "e four"
    assert "1. e4" in journal.pgn_path.read_text()


def test_journal_pairs_what_was_heard_with_what_it_became(tmp_path: Any) -> None:
    """This pairing is the whole point. A move that is legal, in the game, and
    wrong is invisible in a PGN; here it sits next to the words that made it."""
    journal = Journal(directory=tmp_path, name="pairing")
    journal.heard("child", "night to f three", "move", "g1f3", normalised="N f3")

    entry = json.loads(journal.events.read_text().splitlines()[0])
    assert entry["raw"] == "night to f three"
    assert entry["move"] == "g1f3"
    assert entry["normalised"] == "N f3"


def test_journal_records_corrections_with_both_positions(tmp_path: Any) -> None:
    """Corrections are the moments either side of which a desync appears."""
    journal = Journal(directory=tmp_path, name="corrections")
    journal.correction("position edited", "before-fen", "after-fen")

    entry = json.loads(journal.events.read_text().splitlines()[0])
    assert entry["fen_before"] == "before-fen"
    assert entry["fen_after"] == "after-fen"


def test_pgn_is_rewritten_not_appended(tmp_path: Any) -> None:
    """A position edit clears the move stack. An appended file would then hold
    two unrelated fragments with no marker between them."""
    journal = Journal(directory=tmp_path, name="rewrite")
    board = chess.Board()
    board.push_san("e4")
    journal.write_pgn(board)
    board.push_san("e5")
    journal.write_pgn(board)

    text = journal.pgn_path.read_text()
    assert text.count("[Event") == 1
    assert "1. e4 e5" in text


def test_edited_position_still_produces_a_readable_pgn(tmp_path: Any) -> None:
    journal = Journal(directory=tmp_path, name="edited")
    board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    journal.write_pgn(board)

    text = journal.pgn_path.read_text()
    assert "SetUp" in text and "FEN" in text


def test_logging_failure_does_not_stop_the_game(tmp_path: Any) -> None:
    """Losing a game to a logging error would be a poor trade for diagnostics."""
    journal = Journal(directory=tmp_path / "sub", name="broken")
    journal.events = tmp_path / "no-such-directory" / "x.jsonl"
    journal.record("note", message="this cannot be written")  # must not raise
    assert journal._broken


def test_disabled_journal_writes_nothing(tmp_path: Any) -> None:
    journal = Journal(directory=tmp_path, name="off", enabled=False)
    journal.start(level="cub")
    journal.write_pgn(chess.Board())
    assert not journal.events.exists()
    assert not journal.pgn_path.exists()
