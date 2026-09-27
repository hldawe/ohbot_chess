# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The body: everything physical, and the only place the robot library is used.

This layer speaks in poses, gestures and gaze. It knows nothing about chess.
Keeping it that way is what made the previous build survive an SDK change with
a single file edit, and it is the seam most worth protecting here.

Above it sits presentation.py, which knows about chess but not about servos.
The two change for different reasons -- library churn versus coaching tone --
so neither should force an edit to the other.

Two implementations:

    MockBody   prints what it would have done. Used by --mock and by the whole
               test suite, which therefore needs no robot and no fake serial.
    OhbotBody  the real thing.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Sequence
from types import TracebackType
from typing import Any, Literal, Protocol, runtime_checkable

from . import config, serial_safe
from . import expression as ex


@runtime_checkable
class Body(Protocol):
    """What presentation.py is allowed to ask of a robot."""

    speaking: threading.Event

    def speak(self, text: str, *, pose: str | None = ..., gesture: str | None = ...) -> None: ...
    def express(self, pose: str) -> None: ...
    def perform(self, gesture: str, *, blocking: bool = ...) -> None: ...
    def gaze(self, x: float, y: float) -> None: ...
    def look_at(self, target: str) -> None: ...
    def look_at_square(self, square: str) -> None: ...
    def attend(self, on: bool = ...) -> None: ...
    def set_state(self, state: str) -> None: ...
    def recentre(self) -> None: ...


# -- mock -------------------------------------------------------------------


class MockBody:
    """A body that prints. Runs the entire game with no hardware."""

    def __init__(self, verbose: bool = True, **_: Any) -> None:
        self.verbose = verbose
        self.speaking = threading.Event()
        self.said: list[str] = []
        self.poses: list[str] = []
        self.gestures: list[str] = []
        self.gazes: list[tuple[float, float]] = []
        self.states: list[str] = []
        self.board_gaze = ex.BoardGaze()
        self.has_headroll = True
        self.has_eyes = True

    def __enter__(self) -> MockBody:
        return self

    def __exit__(self, *exc: Any) -> Literal[False]:
        return False

    def speak(self, text: str, *, pose: str | None = None, gesture: str | None = None) -> None:
        if not text or not text.strip():
            return
        if pose:
            self.express(pose)
        if gesture:
            self.perform(gesture)
        self.speaking.set()
        try:
            self.said.append(text)
            if self.verbose:
                print(f"  ohbot: {text}")
        finally:
            self.speaking.clear()

    def express(self, pose: str) -> None:
        ex.pose(pose, self.has_headroll)  # validates the name
        self.poses.append(pose)

    def perform(self, gesture: str, *, blocking: bool = False) -> None:
        ex.gesture(gesture, self.has_headroll)  # validates the name
        self.gestures.append(gesture)

    def gaze(self, x: float, y: float) -> None:
        self.gazes.append((x, y))

    def look_at(self, target: str) -> None:
        x, y = ex.LOOK_DIRECTIONS.get(target, (5, 5))
        self.gaze(x, y)

    def look_at_square(self, square: str) -> None:
        x, y = self.board_gaze.square(square)
        self.gaze(x, y)

    def attend(self, on: bool = True) -> None:
        self.states.append("attending" if on else "not_attending")

    def set_state(self, state: str) -> None:
        self.states.append(state)

    def recentre(self) -> None:
        self.gaze(5, 5)


# -- the real robot ---------------------------------------------------------


class OhbotBody:
    """The Ohbot head.

    Used as a context manager so motors are always released:

        with OhbotBody() as body:
            body.speak("Your move.", pose="pleased")
    """

    def __init__(
        self,
        idle: bool = True,
        has_headroll: bool | None = None,
        has_eyes: bool = False,
        eye_colours: dict[str, Sequence[int]] | None = None,
        board_gaze: ex.BoardGaze | None = None,
    ) -> None:
        from ohbot import ohbot  # imported here so the module loads without it

        self._ohbot = ohbot

        # None means "work it out"; True/False is an explicit override for when
        # the detection is wrong.
        self.has_headroll = detect_headroll(ohbot) if has_headroll is None else has_headroll
        # NOT detectable: setEyeColour writes serial with no readback, so a
        # missing accessory is indistinguishable from a fitted one. Config only.
        self.has_eyes = has_eyes

        self.colours = {k: tuple(v) for k, v in (eye_colours or config.EYE_COLOURS).items()}
        self.board_gaze = board_gaze or ex.BoardGaze()

        self.speaking = threading.Event()
        self._attending = threading.Event()
        self._stop = threading.Event()
        self._idle_thread: threading.Thread | None = None
        self._gesture_thread: threading.Thread | None = None
        self._gesture_lock = threading.Lock()
        self._want_idle = idle

    # -- lifecycle -----------------------------------------------------

    def __enter__(self) -> OhbotBody:
        # Must happen before any thread touches a motor.
        serial_safe.install(self._ohbot)
        self._ohbot.reset()
        self.express("neutral")
        self.set_state("listening")
        if self._want_idle:
            self._idle_thread = threading.Thread(target=self._idle_loop, daemon=True)
            self._idle_thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        self._stop.set()
        for thread in (self._idle_thread, self._gesture_thread):
            if thread is not None:
                thread.join(timeout=2)
        try:
            if self.has_eyes:
                self._ohbot.setEyeColour(*self.colours["off"])
            self._ohbot.reset()
        finally:
            self._ohbot.close()  # detach motors so they stop drawing current
        return False

    # -- speech --------------------------------------------------------

    def speak(self, text: str, *, pose: str | None = None, gesture: str | None = None) -> None:
        """Say something, optionally with a face and a movement under it.

        The gesture is launched first and plays DURING the speech. Afterwards
        the aiming axes are recentred, because poses that tilt the head for
        character leave that tilt in place and it compounds utterance after
        utterance until the robot is addressing the wall.
        """
        if not text or not text.strip():
            return
        if pose:
            self.express(pose)

        self.speaking.set()
        try:
            self.set_state("speaking")
            if gesture:
                self.perform(gesture)  # non-blocking: runs beneath the audio
            self._ohbot.say(text)  # blocks until the audio has finished
        finally:
            self.speaking.clear()
            thread = self._gesture_thread
            if thread is not None:
                thread.join(timeout=2)  # don't fight it mid-keyframe
            self.recentre()

    # -- expression ----------------------------------------------------

    def express(self, pose: str) -> None:
        for motor, position in ex.pose(pose, self.has_headroll).items():
            self._move(motor, position, 4)

    def perform(self, gesture: str, *, blocking: bool = False) -> None:
        """Play a keyframe sequence.

        Non-blocking by default so it runs underneath speech. If a gesture is
        already running the new one is DROPPED rather than queued: joining the
        previous thread would block the caller -- and therefore delay speech --
        for as long as the old gesture had left to run.
        """
        frames = ex.gesture(gesture, self.has_headroll)
        if blocking:
            self._play(frames)
            return

        with self._gesture_lock:
            running = self._gesture_thread
            if running is not None and running.is_alive():
                return
            thread = threading.Thread(target=self._play, args=(frames,), daemon=True)
            self._gesture_thread = thread
            thread.start()

    def _play(self, frames: Sequence[tuple[int, float, float, float]]) -> None:
        for motor, position, speed, hold in frames:
            if self._stop.is_set():
                return
            self._move(motor, position, speed)
            time.sleep(hold)

    # -- gaze ----------------------------------------------------------

    def gaze(self, x: float = 5, y: float = 5, speed: float = 6) -> None:
        for motor, position in ex.gaze_positions(x, y).items():
            self._move(motor, position, speed)

    def look_at(self, target: str) -> None:
        """Look somewhere named: 'child', 'board', 'away'."""
        x, y = ex.LOOK_DIRECTIONS.get(target, (5, 5))
        self._look(x, y)

    def look_at_square(self, square: str) -> None:
        """Look at a board square, if the board has been calibrated.

        Uncalibrated this resolves to the fixed 'board' direction, which is
        what the previous hardware always did. The call site exists from day
        one either way -- retrofitting it later would mean touching every
        announcement path in the presentation layer.
        """
        x, y = self.board_gaze.square(square)
        self._look(x, y)

    def _look(self, x: float, y: float) -> None:
        eyes, head = ex.look_targets(x, y, has_headroll=self.has_headroll)

        def run() -> None:
            for motor, position in eyes.items():
                self._move(motor, position, 8)  # eyes snap
            time.sleep(0.12)  # the lag that sells it as a glance
            for motor, position in head.items():
                self._move(motor, position, 3)  # head follows, slower

        threading.Thread(target=run, daemon=True).start()

    def recentre(self, speed: float = 2) -> None:
        """Return the aiming axes to centre so the robot faces the person.

        Deliberately slow: snapping back reads as a twitch, settling reads as
        relaxing. The emotional face -- lids, pitch -- is left alone.
        """
        for motor in ex.ORIENTATION:
            self._move(motor, 5, speed)

    # -- state ---------------------------------------------------------

    def attend(self, on: bool = True) -> None:
        """Backchannel mode: nod and blink while the CHILD is talking.

        Looking attentive while being spoken to does more for the illusion of
        presence than anything the robot does on its own turn.
        """
        self.set_state("listening")
        if on:
            self.express("neutral")
            self._attending.set()
        else:
            self._attending.clear()

    def set_state(self, state: str) -> None:
        """Signal state via the eye LEDs, where they exist.

        Never the ONLY signal of anything -- see presentation.py, which always
        pairs a state change with a pose or an utterance. Without the
        Illuminating Eyes accessory this is a no-op and nothing is lost.
        """
        if not self.has_eyes:
            return
        self._ohbot.setEyeColour(*self.colours.get(state, self.colours["off"]))

    # -- internals -----------------------------------------------------

    def _move(self, motor: int, position: float, speed: float = 5) -> None:
        if self._stop.is_set():
            return
        # Lip sync owns the mouth while speaking.
        if motor in ex.MOUTH and self.speaking.is_set():
            return
        if motor == ex.HEADROLL and not self.has_headroll:
            return
        self._ohbot.move(motor, position, speed)

    def _idle_loop(self) -> None:
        """Blink, drift and backchannel-nod so it never looks crashed.

        Idle motion continues during speech -- the write lock makes that safe,
        and freezing is what makes a robot read as a speaker with a face.

        Idle gestures go through perform() rather than calling _play directly,
        so they respect the one-gesture-at-a-time rule. Calling _play here
        would let an idle blink run concurrently with a deliberate gesture, and
        both drive the eyelids.
        """
        now = time.time()
        next_blink = now + random.uniform(*config.BLINK_INTERVAL)
        next_drift = now + random.uniform(*config.DRIFT_INTERVAL)
        next_backchannel = now + random.uniform(*config.BACKCHANNEL_INTERVAL)

        while not self._stop.is_set():
            time.sleep(0.15)
            now = time.time()

            if now >= next_blink:
                self.perform("blink")
                next_blink = now + random.uniform(*config.BLINK_INTERVAL)

            elif self._attending.is_set() and now >= next_backchannel:
                # A small nod while being spoken to reads as "I'm following".
                self.perform("slow_nod")
                next_backchannel = now + random.uniform(*config.BACKCHANNEL_INTERVAL)

            elif now >= next_drift and not self.speaking.is_set():
                motor = random.choice([ex.HEADTURN, ex.HEADNOD])
                self._move(motor, random.randint(4, 6), 2)
                next_drift = now + random.uniform(*config.DRIFT_INTERVAL)


# -- hardware detection -----------------------------------------------------


def detect_headroll(ohbot_module: Any) -> bool:
    """Whether a head-roll servo is fitted.

    The library reads ohbotData/MotorDefinitionsv21.omd at init and records a
    type per motor. An absent servo has no type. This is a read of that table,
    not a probe -- nothing moves.

    Detection can be wrong (a miswired robot, an edited definitions file), so
    every caller can override it explicitly. On any doubt this returns True,
    because a fitted servo that goes unused is a lost head-cock, while an
    unfitted one that gets driven is only an ignored command.
    """
    try:
        motor_type = getattr(ohbot_module, "motorType", None)
        if not motor_type or len(motor_type) <= ex.HEADROLL:
            return True
        return bool(motor_type[ex.HEADROLL])
    except Exception:
        return True
