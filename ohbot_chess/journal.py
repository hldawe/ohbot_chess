# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Recording what actually happened, so a desync can be diagnosed afterwards.

WHY

When the robot's board and the physical board drift apart, the interesting
information is what was HEARD and what it was PARSED TO -- and both are gone by
the time anyone notices, several moves later. A PGN alone does not help: it
records the moves the code believed in, which is exactly the thing under
suspicion.

So two files per game:

    <name>.jsonl   one line per event: raw input, what it parsed to, the FEN
                   after, and why the parse went the way it did
    <name>.pgn     the game as played, readable by any chess tool

Both are written as the game goes, not at the end, so a crash or a pulled USB
cable still leaves everything up to that point.

Logging never interrupts play. Every write is wrapped: a full disk or a
read-only directory degrades to a warning, because losing a game to a logging
error would be a poor trade for diagnostics.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chess
import chess.pgn


class Journal:
    """Writes a JSONL event log and a PGN alongside it."""

    def __init__(
        self,
        directory: str | Path = "logs",
        name: str | None = None,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.started = datetime.now(UTC)
        stamp = self.started.strftime("%Y%m%d-%H%M%S")
        self.name = name or f"game-{stamp}"
        self.directory = Path(directory)
        self.events = self.directory / f"{self.name}.jsonl"
        self.pgn_path = self.directory / f"{self.name}.pgn"
        self._broken = False
        self._headers: dict[str, str] = {}

        if self.enabled:
            self._ensure_directory()

    def _ensure_directory(self) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._warn(f"cannot create {self.directory}: {e}")
            self.enabled = False

    def _warn(self, message: str) -> None:
        # Once only. A logging problem that reappears every move would bury the
        # game itself in warnings.
        if not self._broken:
            print(f"[journal] {message}", file=sys.stderr)
            print("[journal] carrying on without a log.", file=sys.stderr)
            self._broken = True

    # -- events --------------------------------------------------------

    def record(self, kind: str, **fields: Any) -> None:
        """Append one event. Never raises."""
        if not self.enabled or self._broken:
            return
        entry = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "monotonic": round(time.monotonic(), 3),
            "kind": kind,
            **fields,
        }
        try:
            with self.events.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
        except OSError as e:
            self._warn(f"could not write {self.events}: {e}")

    def start(self, **settings: Any) -> None:
        self.record("start", **settings)
        self._headers = {str(k): str(v) for k, v in settings.items()}

    def heard(self, who: str, raw: str, parsed_kind: str, move: str | None, **extra: Any) -> None:
        """What arrived, and what it became.

        This pairing is the whole point of the log. A move that is legal, in
        the game, and wrong is invisible in a PGN; here it sits next to the
        words that produced it.
        """
        self.record(
            "input",
            who=who,
            raw=raw,
            parsed=parsed_kind,
            move=move,
            **extra,
        )

    def move(self, who: str, san: str, uci: str, fen: str, **extra: Any) -> None:
        self.record("move", who=who, san=san, uci=uci, fen=fen, **extra)

    def correction(self, what: str, before: str, after: str, **extra: Any) -> None:
        """A position edit, an undo, or a refused move -- anything that rewrites
        history. These are the moments either side of which a desync usually
        appears, so they are logged with the FEN on both sides."""
        self.record("correction", what=what, fen_before=before, fen_after=after, **extra)

    def note(self, message: str, **extra: Any) -> None:
        self.record("note", message=message, **extra)

    def finish(self, result: str, fen: str) -> None:
        self.record("finish", result=result, fen=fen)

    # -- pgn -----------------------------------------------------------

    def write_pgn(self, board: chess.Board, result: str = "*", **headers: Any) -> None:
        """Rewrite the PGN from the current move stack.

        Rewritten in full each time rather than appended to, because a position
        edit clears the stack and an appended file would then contain two
        unrelated fragments with no marker between them.
        """
        if not self.enabled or self._broken:
            return

        game = chess.pgn.Game()
        game.headers["Event"] = "ohbot_chess"
        game.headers["Site"] = "Ohbot"
        game.headers["Date"] = self.started.strftime("%Y.%m.%d")
        game.headers["Result"] = result
        for key, value in {**self._headers, **headers}.items():
            game.headers[str(key)] = str(value)

        replay = chess.Board()
        if board.move_stack:
            # The stack may not start from the initial position if the board
            # was edited mid-game; fall back to recording the FEN instead of
            # producing a PGN that does not replay.
            try:
                node: Any = game
                for move in board.move_stack:
                    node = node.add_variation(move)
                    replay.push(move)
            except (AssertionError, ValueError):
                game.headers["FEN"] = board.fen()
                game.headers["SetUp"] = "1"
        else:
            game.headers["FEN"] = board.fen()
            game.headers["SetUp"] = "1"

        try:
            self.pgn_path.write_text(str(game) + "\n", encoding="utf-8")
        except OSError as e:
            self._warn(f"could not write {self.pgn_path}: {e}")

    # -- summary -------------------------------------------------------

    def where(self) -> str:
        if not self.enabled:
            return "logging is off"
        return f"{self.events} and {self.pgn_path}"
