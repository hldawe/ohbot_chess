#!/usr/bin/env python3
# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check the voice path end to end, before trusting it in a game.

    python tools/check_speech.py --vosk-model ./model

Four things, in the order they fail:

  1. Is the Piper voice present and does it produce a WAV the lip sync can read?
  2. Is the microphone actually delivering audio, or is the OS handing us silence?
  3. Does the recogniser hear you?
  4. Does a per-turn grammar constrain it to legal moves only?

Step 4 is the one worth watching. It is the reason this app uses a closed-
grammar recogniser rather than an open-vocabulary one, and seeing an illegal
move refused at the RECOGNISER rather than at the parser is the demonstration.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chess  # noqa: E402

from ohbot_chess import config, moves, speech  # noqa: E402
from ohbot_chess import listener as listener_mod
from ohbot_chess.chess_core import GameState  # noqa: E402

OK = "  ok  "
BAD = " FAIL "


def check_voice(voice: str, directory: str) -> bool:
    print("1. Speech output")
    if not speech.available(voice, directory):
        print(f"  [{BAD}] missing: {', '.join(speech.missing(voice, directory))}")
        print("         Download the .onnx and .onnx.json from")
        print("         https://huggingface.co/rhasspy/piper-voices")
        return False

    try:
        engine = speech.PiperTTS(voice, directory)
        path = engine.synth("Knight to f three.", "speech_check.wav")
    except Exception as e:
        print(f"  [{BAD}] {e}")
        return False

    import wave

    with wave.open(path) as handle:
        width, channels, rate = (
            handle.getsampwidth(),
            handle.getnchannels(),
            handle.getframerate(),
        )
        seconds = handle.getnframes() / rate

    print(f"  [{OK}] {voice}: {rate} Hz, {channels} ch, {width * 8}-bit, {seconds:.2f}s")
    if width != 2 or channels != 1:
        # The viseme loop indexes buffer[i] + buffer[i+1]*256 and assumes mono.
        print(f"  [{BAD}] lip sync needs 16-bit mono. The mouth will move wrongly.")
        return False
    if seconds < config.TAIL_SILENCE_SECONDS:
        print(f"  [{BAD}] no silent tail -- short replies will raise IndexError.")
        return False
    print(f"         written to {path}")
    return True


def check_microphone(model_dir: str, device: int | None) -> object | None:
    print("\n2. Microphone")
    try:
        listener = listener_mod.Listener(model_dir=model_dir, device=device)
    except listener_mod.VoskUnavailable as e:
        print(f"  [{BAD}] {e}")
        return None

    try:
        listener.calibrate()
    except listener_mod.MicrophoneBlocked as e:
        print(f"  [{BAD}] {e}")
        return None
    except Exception as e:
        print(f"  [{BAD}] {e}")
        return None

    print(f"  [{OK}] noise threshold {listener.threshold:.5f}")
    return listener


def check_recognition(listener: object) -> None:
    print("\n3. Recognition, open grammar")
    print("   Say anything.")
    grammar = listener_mod.build_grammar(["hello", "testing", "one two three"])
    heard = listener.listen(grammar, timeout=10.0)  # type: ignore[attr-defined]
    print(f"  [{OK if heard else BAD}] heard: {heard!r}")


def check_vocabulary(listener: object) -> bool:
    """Does the model actually know the words the grammar is built from?

    This is the most likely reason for a recogniser that runs but never matches
    anything. A closed grammar containing a word the model has never seen is
    silently broken: Vosk logs to its C stderr and carries on.
    """
    print("\n4. Grammar vocabulary")

    state = GameState("white")
    phrases: list[str] = []
    for move in state.legal_moves():
        phrases.extend(moves.spoken_forms(move, state.board))
    phrases.extend(listener_mod.CONTROL_WORDS)

    words = {w for phrase in phrases for w in phrase.split()}
    try:
        missing = listener_mod.missing_words(
            listener._model,  # type: ignore[attr-defined]
            listener._recogniser_class,  # type: ignore[attr-defined]
            listener.sample_rate,  # type: ignore[attr-defined]
            words,
        )
    except Exception as e:
        print(f"  [{BAD}] could not check: {e}")
        return True

    if not missing:
        print(f"  [{OK}] all {len(words)} words are in the model's vocabulary")
        return True

    print(f"  [{BAD}] the model does not know: {', '.join(missing)}")
    print("         A closed grammar containing an unknown word matches")
    print("         nothing. If these are single letters, the model's lexicon")
    print("         has no entry for them and the phrasings that use them")
    print("         cannot be recognised.")
    return False


def check_grammar(listener: object) -> None:
    print("\n5. Recognition, constrained to legal moves")

    state = GameState("white")
    phrases: list[str] = []
    for move in state.legal_moves():
        phrases.extend(moves.spoken_forms(move, state.board))
    grammar = listener_mod.build_grammar(phrases)

    print(f"   {len(state.legal_moves())} legal moves -> {len(phrases)} phrasings.")
    print("   Try a legal move: 'e four' or 'knight to f three'.")
    heard = listener.listen(grammar, timeout=12.0)  # type: ignore[attr-defined]
    print(f"   heard: {heard!r}")

    if heard:
        parsed = moves.parse(heard, state.board)
        print(f"   parsed as: {parsed.kind} {parsed.move}")
        if parsed.ok:
            print(f"  [{OK}] round trip complete")
        else:
            print(f"  [{BAD}] the recogniser returned something the parser rejects")

    print("\n   Now try an ILLEGAL move: 'knight to f six'.")
    print("   It should come back empty -- the recogniser has never heard of it.")
    heard = listener.listen(grammar, timeout=12.0)  # type: ignore[attr-defined]
    if heard:
        parsed = moves.parse(heard, chess.Board())
        print(f"   heard {heard!r} -> {parsed.kind}")
        if parsed.ok:
            print(f"  [{BAD}] an illegal move got through the grammar")
        else:
            print(f"  [{OK}] not accepted as a move")
    else:
        print(f"  [{OK}] refused at the recogniser, which is the point")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", default=config.DEFAULT_VOICE)
    parser.add_argument("--voice-dir", default="voices")
    parser.add_argument("--vosk-model", default=config.VOSK_MODEL_DIR)
    parser.add_argument("--mic", type=int, default=None)
    parser.add_argument("--skip-mic", action="store_true")
    args = parser.parse_args()

    ok = check_voice(args.voice, args.voice_dir)
    if args.skip_mic:
        return 0 if ok else 1

    listener = check_microphone(args.vosk_model, args.mic)
    if listener is None:
        return 1

    check_recognition(listener)
    check_vocabulary(listener)
    check_grammar(listener)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
