# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Make the Ohbot library's serial writes thread-safe.

WHY THIS EXISTS

ohbot._serwrite() guards concurrent writes with a `writing` boolean on Windows
and Linux -- but on macOS there is no guard at all, and say() drives the lip
motor from its own thread while audio plays. So any second thread moving motors
during speech can interleave with the lip-sync stream and cut a motor command
in half.

The obvious fix is to freeze other motion while speaking. That is exactly the
wrong trade here: gesturing WHILE speaking is what makes the robot read as
present rather than as a speaker with a face.

The real fix is small, because all of the library's serial writes funnel
through _serwrite and a standard move() emits exactly one newline-terminated
message per call:

    m0<motor>,<position>,<speed>\\n

So a lock around _serwrite gives MESSAGE-LEVEL atomicity. Threads may still
interleave whole commands -- that is fine, the firmware parses line by line --
but a command can no longer be cut in half by another thread's bytes.

Install before starting any thread that moves motors.
"""

from __future__ import annotations

import threading
from typing import Any

# Reentrant on purpose. A caller may hold the lock across a whole
# write-then-read transaction (reading a sensor does exactly that), and the
# inner _serwrite would then deadlock on a plain Lock.
lock = threading.RLock()

# Keyed by module identity rather than kept as one global. There is only ever
# one robot in practice, but a single global original means installing against
# one module and uninstalling against another silently restores the wrong
# function -- which is a genuinely confusing failure to debug, and free to
# avoid.
_originals: dict[int, Any] = {}


def install(ohbot_module: Any) -> threading.RLock:
    """Wrap the module's _serwrite so writers cannot interleave mid-message.

    Idempotent: calling twice does not double-wrap. Takes the module as an
    argument rather than importing it, so this file stays importable and
    testable with no library present.
    """
    key = id(ohbot_module)
    if key in _originals:
        return lock

    original = ohbot_module._serwrite
    _originals[key] = original

    def _locked_serwrite(s: str) -> None:
        with lock:
            original(s)

    ohbot_module._serwrite = _locked_serwrite
    return lock


def uninstall(ohbot_module: Any) -> None:
    """Restore the unguarded write. Mainly here to prove the lock matters."""
    original = _originals.pop(id(ohbot_module), None)
    if original is not None:
        ohbot_module._serwrite = original


def is_installed(ohbot_module: Any = None) -> bool:
    """Whether the lock is installed -- on a given module, or on anything."""
    if ohbot_module is None:
        return bool(_originals)
    return id(ohbot_module) in _originals
