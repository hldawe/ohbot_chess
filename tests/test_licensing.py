# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Licensing hygiene, checked automatically.

The FSF recommends a per-file notice, and per-file notices are the kind of
thing that stays complete for exactly as long as someone remembers to add one.
So it is a test rather than a convention.
"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPDX = "SPDX-License-Identifier: GPL-3.0-or-later"


def source_files() -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    for folder in ("ohbot_chess", "tools", "tests"):
        paths.extend(sorted((ROOT / folder).glob("*.py")))
    return paths


def test_there_are_source_files_to_check() -> None:
    assert len(source_files()) > 20


@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
def test_every_source_file_carries_the_notice(path: pathlib.Path) -> None:
    assert SPDX in path.read_text(), f"{path.name} has no licence notice"


def test_the_licence_text_is_present_and_whole() -> None:
    licence = (ROOT / "LICENSE").read_text()
    assert "GNU GENERAL PUBLIC LICENSE" in licence
    assert "Version 3, 29 June 2007" in licence
    # The full text runs to well over 600 lines; a truncated copy is worse than
    # none, because it looks like it has been checked.
    assert len(licence.splitlines()) > 600


def test_notice_records_why_stockfish_is_not_the_reason() -> None:
    """The distinction is the whole analysis and is easy to lose in an edit.

    python-chess is imported, so it sets the licence. Stockfish is a separate
    binary over UCI and sets nothing. A future reader who conflates the two
    will reach the wrong conclusion about what may be changed.
    """
    notice = (ROOT / "NOTICE").read_text()
    assert "python-chess" in notice
    assert "separate binary" in notice
