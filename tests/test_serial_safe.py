# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The write lock -- the one piece that makes gesturing during speech safe."""

from __future__ import annotations

import threading
import types
from typing import Any

from ohbot_chess import serial_safe


class Recorder(types.ModuleType):
    """A module whose _serwrite is slow enough to interleave if unguarded."""

    def __init__(self, delay: float = 0.0) -> None:
        super().__init__("recorder")
        self.delay = delay
        self.chunks: list[str] = []
        self._active = 0
        self.overlaps = 0

    def _serwrite(self, s: str) -> None:
        self._active += 1
        if self._active > 1:
            self.overlaps += 1
        if self.delay:
            import time

            time.sleep(self.delay)
        self.chunks.append(s)
        self._active -= 1


def test_install_is_idempotent() -> None:
    module = Recorder()
    serial_safe.uninstall(module)
    first = serial_safe.install(module)
    wrapped = module._serwrite
    second = serial_safe.install(module)
    assert first is second
    assert module._serwrite is wrapped, "double wrapped"
    serial_safe.uninstall(module)


def test_lock_is_reentrant() -> None:
    """A caller may hold the lock across a whole write-then-read transaction.

    Reading a sensor does exactly that, and the inner _serwrite would deadlock
    on a plain Lock.
    """
    module = Recorder()
    serial_safe.install(module)
    try:
        with serial_safe.lock:
            module._serwrite("m00,5,5\n")  # would deadlock if not reentrant
        assert module.chunks == ["m00,5,5\n"]
    finally:
        serial_safe.uninstall(module)


def test_concurrent_writers_do_not_overlap() -> None:
    """Message-level atomicity.

    Threads may still interleave whole commands -- fine, the firmware parses
    line by line -- but a command must not be cut in half by another thread's
    bytes.
    """
    module = Recorder(delay=0.002)
    serial_safe.install(module)
    try:
        threads = [
            threading.Thread(target=module._serwrite, args=(f"m0{i},5,5\n",)) for i in range(12)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert module.overlaps == 0, f"{module.overlaps} overlapping writes"
        assert len(module.chunks) == 12
    finally:
        serial_safe.uninstall(module)


def test_without_the_lock_writers_do_overlap() -> None:
    """Proves the lock is load-bearing rather than decorative.

    If this test ever fails, the concurrency problem it guards against has gone
    away and the lock could be reconsidered. Until then it has not.
    """
    module = Recorder(delay=0.002)
    threads = [threading.Thread(target=module._serwrite, args=(f"m0{i},5,5\n",)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert module.overlaps > 0


def test_uninstall_restores_the_original() -> None:
    module = Recorder()
    original = module._serwrite
    serial_safe.install(module)
    assert module._serwrite != original
    serial_safe.uninstall(module)
    # Compared with == rather than `is`: attribute access on an instance builds
    # a fresh bound-method object each time, so two accesses to the same method
    # are never the same object but do compare equal.
    assert module._serwrite == original
    assert not serial_safe.is_installed(module)


def test_originals_are_tracked_per_module() -> None:
    """One global original would restore the wrong function across modules."""
    a, b = Recorder(), Recorder()
    original_b = b._serwrite

    serial_safe.install(a)
    serial_safe.install(b)
    serial_safe.uninstall(a)

    assert serial_safe.is_installed(b), "uninstalling A disarmed B"
    serial_safe.uninstall(b)
    assert b._serwrite == original_b


def test_module_imports_without_the_robot_library() -> None:
    """install() takes the module as an argument rather than importing it.

    That keeps this file importable and testable with no library present, which
    matters because it is the file most likely to be read by someone deciding
    whether the lock is really necessary.
    """
    import inspect

    source = inspect.getsource(serial_safe)
    assert "from ohbot import" not in source


def _noop(_: Any) -> None:
    pass
