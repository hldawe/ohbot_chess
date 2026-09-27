# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Documentation that goes stale silently.

A README is the one file nothing checks, so it drifts. These are the two claims
in it that are cheap to verify and expensive to get wrong: the list of flags,
and whether the command to actually run the thing appears anywhere findable.
"""

from __future__ import annotations

import pathlib
import re

from ohbot_chess import cli

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

FLAG_IN_TABLE = re.compile(r"\| `(--[a-z-]+)`")


def readme() -> str:
    return README.read_text()


def parser_flags() -> set[str]:
    flags = {option for action in cli.build_parser()._actions for option in action.option_strings}
    return flags - {"-h", "--help"}


def test_flag_table_lists_every_flag() -> None:
    """An undocumented flag is a feature nobody finds."""
    missing = parser_flags() - set(FLAG_IN_TABLE.findall(readme()))
    assert not missing, f"not in the README flag table: {sorted(missing)}"


def test_flag_table_invents_nothing() -> None:
    """A documented flag that doesn't exist is worse than no documentation."""
    invented = set(FLAG_IN_TABLE.findall(readme())) - parser_flags()
    assert not invented, f"documented but not real: {sorted(invented)}"


def test_the_run_command_is_findable() -> None:
    """It was once mentioned only mid-paragraph, three sections apart.

    Someone landing on the repo should meet the command before they meet the
    architecture, so it has to appear near the top and not only as an aside to
    a diagnostic tool.
    """
    text = readme()
    first = text.index("python -m ohbot_chess.cli")
    assert first < 1200, "the run command is buried below the first screenful"


def test_there_is_a_section_for_running_it() -> None:
    assert "\n## Play\n" in readme()


def test_every_command_in_the_readme_actually_parses() -> None:
    """A copy-pasteable command that isn't valid is worse than no example.

    The README is now mostly commands to copy, so a renamed or removed flag
    breaks the documentation silently while every other test still passes.
    """
    import shlex

    parser = cli.build_parser()
    commands = re.findall(r"^(python -m ohbot_chess\.cli[^\n#]*)", readme(), re.M)
    assert len(commands) > 10, "the README has stopped showing commands"

    for command in commands:
        arguments = shlex.split(command)[3:]  # drop "python -m ohbot_chess.cli"
        try:
            parser.parse_args(arguments)
        except SystemExit:  # argparse exits rather than raising on bad input
            raise AssertionError(f"README command is not valid: {command}") from None


def test_every_difficulty_level_has_a_command() -> None:
    """The levels are the thing people most want to change first."""
    text = readme()
    from ohbot_chess import config

    for level in config.LEVEL_ORDER:
        assert f"--level {level}" in text, f"no copy-paste command for {level}"


def test_mock_mode_is_offered_early() -> None:
    """The zero-setup path is the one that gets someone to a working game."""
    text = readme()
    assert text.index("--mock") < text.index("## Setup")
