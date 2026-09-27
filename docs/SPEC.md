# ohbot_chess — specification

**Status:** revision 2. Implemented; this describes what was built and why.
**Audience:** implementer (human or agent), and anyone auditing the design.

Changes from revision 1 are marked **[r2]**.

---

## 1. Premise

Ohbot has no arms. So Ohbot is the brain, the eyes and the face; the person
opposite is its hands. It computes a move, announces it, and waits for the
piece to be moved on a physical board.

This is a port of `reachy_chess`, built on the same premise for a Reachy Mini.
The game logic carries over almost unchanged. The body, the speech path and the
listener are rebuilt for different hardware.

Everything runs locally. No cloud services, no API keys, no network required
after setup.

---

## 2. What changes from `reachy_chess`, and why

| | Reachy Mini | Ohbot | Consequence |
|---|---|---|---|
| Compute | On-board CM4 | Tethered to host | Stockfish unconstrained; analysis depth freed from play strength (§6) |
| Audio out | On-board speaker | **Host speaker** | Voice is not co-located with the mouth (§8) |
| Camera | Standard | Optional accessory | **No vision cross-check in v1** (§9) |
| Face | Head + antennas | 8 servos: eyes, lids, mouth, head | Far richer expression; gaze independent of head (§7) |
| Testing | Hardware-dependent | Fakeable in `sys.modules` | Full game loop in CI (§11) |

The two that drove real design work were the missing camera and the relocated
speaker. Everything else is an improvement or neutral.

---

## 3. Non-goals

- **No language model.** Announcements and coaching come from a curated phrase
  bank. A model cannot hallucinate a move that wasn't played if there is no
  model.
- No cloud anything.
- No vision in v1. Deferred, not designed out (§14).
- No speaker in the head. Accepted; the host speaker is the design.
- No piece manipulation. The robot never touches the board.
- No online play, no PGN import, no opening book beyond Stockfish's own.
- No persistence between sessions.

---

## 4. Layout

```
ohbot_chess/
  config.py          difficulty levels, coaching thresholds, timings
  chess_core.py      GameState, Engine, Coach          [ported ~unchanged]
  moves.py           parsing, spoken normalisation, illegal explanations
  listener.py        Vosk: per-turn grammar, VAD, drain, self-speech gate
  speech.py          Piper, installed over ohbot._generateSpeechFile
  phrases.py         curated announcement and coaching bank
  body.py            Body protocol, MockBody, OhbotBody
  expression.py      poses, gestures, gaze — the vocabulary
  presentation.py    maps game events to expression
  serial_safe.py     the write lock                    [carried over]
  game.py            the turn loop
  cli.py             argument parsing, entry point
tools/
  bringup.py         every motor, plus the two fitted/not-fitted questions
  check_speech.py    the whole voice round trip
  calibrate_gaze.py  two-point board calibration
```

---

## 5. The Body seam

`body.py` defines a `Body` protocol in **physical** terms — poses, gestures,
gaze, speech. It knows nothing about chess. Two implementations: `OhbotBody`
and `MockBody` (terminal output, used by `--mock` and by the whole test suite).

`presentation.py` sits above it, knows about chess but not about servos, and
holds everything that decides "a blunder gets a sympathetic face and a slow
nod".

The split matters because the layers change for different reasons. Library
churn hits `body.py`; coaching tone hits `presentation.py`.

**[r2] `expression.py` imports nothing from the robot library.** Motor numbers
are fixed hardware facts and are written as literals. This diverges from
`reachy_chess` and from the Ohbot hackathon kit, both of which read them from
the library — which meant the vocabulary could not be imported, inspected or
tested without a serial port. A test asserts the absence of the import.

**[r2] `MockBody` validates.** It raises on an unknown pose or gesture rather
than accepting anything. A typo that only surfaces on hardware defeats the
point of having a mock.

---

## 6. The engine

### 6.1 Weakening by sampling, not by depth

Levels weaken Stockfish by sampling a worse move from a full-strength candidate
list. A depth-limited engine blunders tactically while still crushing you
positionally, which plays like nothing human. Weights decay geometrically down
the candidate list, so a mediocre move is common and a terrible one is rare.

**[r2] The decay constant IS the weakness.** Writing `decay = 1 - weakness`
inverts the curve and makes `kitten` the *strongest* setting, because a
weakness of 0.95 gives the top move twenty times the weight of the second.
Every level then plays at full strength. This is worth stating explicitly
because the bug is invisible against a live engine: Stockfish's own move-to-move
variation makes the choices look like they are spreading. It was caught by a
unit test on the sampler, not by playing.

**[r2] Weakening never hangs mate.** Candidates with a losing mate score are
excluded before sampling. Losing on purpose is not gentleness, it is a broken
opponent.

### 6.2 Analysis depth is independent of play strength **[r2]**

`ANALYSIS_DEPTH` is separate from `Level.play_depth`. On the CM4 those competed
for one CPU budget, so weakening play also weakened the coaching. Tethered they
don't compete, so the opponent can be a kitten while the teacher is not.

Bad play is the point; bad advice never is.

### 6.3 Mercy

Below a threshold evaluation the engine widens its candidate list and raises
weakness. It never announces this. Being told you are being pitied is worse
than losing.

### 6.4 Judging

Centipawn loss against the engine's best move, in bands deliberately more
forgiving than an adult analysis tool. Telling a beginner that a 60-centipawn
move was a mistake is technically true and pedagogically useless.

**[r2] The fallback evaluation must be taken from the mover's point of view.**
Taking it from the opponent's and then clamping with `max(0, ...)` scores
Fool's Mate as a *great* move — the clamp hides the sign error completely. A
coaching app that congratulates a child on being mated in two is worse than one
with no coach at all. There is a regression test.

**[r2] "Great" requires there to have been something to get wrong.** A forced
recapture is downgraded to "good". Praising the only legal move is hollow and
children hear it as hollow.

### 6.5 Restraint

Blunders always get a word. Everything else waits for a cooldown. A comment on
every move turns the game into a lecture and drains the meaning from the
comments that matter.

---

## 7. Expression

### 7.1 Carried over

The `_serwrite` lock is non-negotiable. Without it a gesture running during
speech interleaves with the lip-sync thread and corrupts motor commands,
because the vendor library has no concurrency guard on macOS. Message-level
atomicity suffices — one `move()` is one newline-terminated command. Reentrant,
because sensor reads hold it across a write-then-read.

**[r2] The saved original is keyed by module identity, not held as one global.**
There is only ever one robot in practice, but a single global means installing
against one module and uninstalling against another silently restores the wrong
function.

The mouth-ownership rule carries over: while speaking, lip sync owns TOPLIP and
BOTTOMLIP and pose values for those motors are dropped.

### 7.2 Vocabulary

Poses: `neutral`, `thinking`, `pleased`, `sympathetic`, `impressed`,
`concerned`, `playful`.
Gestures: `nod`, `slow_nod`, `tilt`, `lean_in`, `perk_up`, `look_away`,
`blink`, `double_blink`.

Deliberately absent: `double_take`, `shiver`, `recoil`. Nothing at a chessboard
warrants a flinch, and having them available only invites misuse. A test
asserts their absence.

**Restraint is enforced in code, not left to taste.** Routine move
announcements get a face and no gesture; the budget is spent on coaching beats.

### 7.3 Head roll — detected, with a rebuilt fallback

Detection reads the library's motor-definition table. Nothing moves; it is a
read, not a probe. `--headroll yes|no` overrides it, and `tools/bringup.py`
moves the servo and asks, because the table can be wrong.

On doubt, detection returns **present**: a fitted servo left unused loses the
head-cock, whereas an unfitted one that gets driven only produces an ignored
command.

**The fallback rebuilds rather than strips.** `sympathetic` is the pose that
does the most emotional work and it is built on the head-cock. Removing the
motor and leaving the rest gives a blank stare, so the substitute compensates:
lids lower, head drops further, gaze settles just below the child's eyeline.
That reads as attentive-and-serious rather than warm — a downgrade, but a
legible one. **[r2]** `tilt`, which is entirely head-roll, degrades to a small
nod rather than to nothing; a gesture that silently does not happen looks like
a crash.

### 7.4 Eye colour — undetectable, and that's fine

`setEyeColour` writes serial with no readback, so a missing accessory is
indistinguishable from a fitted one. Config flag only, default off.

**No state may ever be signalled by colour alone.** Honour that and the absent
accessory needs no fallback code at all — thinking is also a pose, listening is
also backchannel nodding, your-turn is also an utterance. A test enforces it.

### 7.5 Gaze as board reference **[r2: interface in v1, mapping in v2]**

Ohbot's eyes move independently of its head, so it can look at the square it is
naming and then back at the child. This is the strongest presence win available
on this hardware and the only part of the design with no prior art to port.

**The call site exists from day one.** `look_at_square()` is in the
presentation layer now and resolves against `gaze_calibration.json` if present,
or a fixed downward direction if not. Retrofitting it later would mean touching
every announcement path.

Uncalibrated is a **legitimate shipping state**, not a degraded one. A
miscalibrated gaze is far worse than none: confidently looking at the wrong
square undermines everything else. `tools/calibrate_gaze.py` prints its
resulting square positions so they can be sanity-checked, and says plainly to
delete the file if they look wrong.

---

## 8. Speech out

**[r2] Piper, not Kokoro.** Revision 1 specified Kokoro. Kokoro has no Scottish
voice — its British voices are RP — and voice consistency with the Reachy build
matters more than the marginal speed difference. Two heads with one voice read
as one system.

Piper is also the easier integration: it emits 16-bit PCM natively, so unlike a
float32 engine there is nothing to convert.

**[r2] Require piper-tts >= 1.3.0.** Development moved from `rhasspy/piper`
(MIT, archived October 2025) to `OHF-Voice/piper1-gpl` (GPL-3.0-or-later).
Versions 1.1 and 1.2 depend on a separate `piper-phonemize` package with no
macOS wheel, so `pip install piper-tts` fails outright on a Mac. From 1.3.0
espeak-ng is embedded and the dependency is gone.

The API changed at the same point: `synthesize()` yields `AudioChunk` objects
exposing `audio_int16_bytes`, rather than returning raw bytes or taking a wave
writer. Chunks must be joined — taking the first truncates every utterance —
and their width and channel count are asserted rather than assumed, because a
mismatch does not fail loudly, it moves the mouth to the wrong envelope.

Installed over `ohbot._generateSpeechFile`. `say()` resolves that as a module
global at call time, so rebinding the attribute is the whole integration —
viseme calculation, threading, playback and `untilDone` all keep working.

Two constraints from the viseme code, both handled and both tested:

- It indexes `buffer[i] + buffer[i+1]*256`, so the WAV **must be 16-bit PCM**.
- It loops `range(0, length - chunk, chunk)` then indexes `times[-1]`. Audio
  under ~0.2s leaves that list empty and raises `IndexError`. **"Check." is a
  realistic utterance**, so every clip gets 0.3s of silence appended.

**No output device routing.** Audio goes to the system default. `_playSpeech`
is left alone, which removes a monkeypatch that revision 1 inherited.

### 8.1 The co-location problem

The voice does not come from the thing with the moving mouth. Accepted, not
solved. Lip sync still runs and a synchronised visual is usually enough to
localise the voice to the face — much more so when the robot sits next to the
laptop rather than across the desk. Documented as a known limitation in the
README rather than quietly hoped away.

---

## 9. Board state without a camera

Solved in the interaction rather than in perception. Three mechanisms:

**Confirm-back.** After announcing, the robot waits `PATIENCE_SECONDS` before
asking whether the piece has been moved. Impatience was a real bug on the
previous build — it asked while a hand was still over the board.

**[r2] An empty input means opposite things by channel.** A typed empty line is
someone pressing Enter to say "done". An empty return from a microphone is a
timeout with a hand still busy. `Input.blocking` distinguishes them; conflating
them either ignores the keyboard or nudges constantly.

**Readback on request.** `board` reads the position aloud, grouped by colour
and piece type — sixty-four squares in file order is not followable by ear.
Square names are respelled for speech, since a TTS engine reads "a1"
inconsistently.

**Take-back.** `take that back` reverts a full move pair. Undoing a single ply
would hand the turn to the wrong player.

**[r2] The robot must be able to be TOLD its move is impossible.** This was
missing and it broke a real game. The engine cannot produce an illegal move,
but it can ask for one that cannot be played on the physical board, because the
two boards have drifted and its move is legal only in the position it thinks it
is in. Nothing in the software can detect that — with no camera, only a person
can.

Three separate faults combined to leave no recourse:

- `wait_for_hands` did not handle `undo` at all, so it fell through.
- Its final branch treated any unrecognised reply as "yes, done", which
  silently converted every protest into confirmation.
- The move was pushed onto the board before the wait began, so there was
  nothing to withdraw even conceptually.

Now: a `cannot` command (`that's not legal`, `illegal`, `can't do that`,
`try another`) withdraws the move, adds it to a per-turn exclusion set, and
picks a different one. Unrecognised replies while waiting say so instead of
confirming.

**The exhausted branch must change state.** When every candidate has been
refused, returning from `robot_turn` left it still the robot's turn and `play()`
called straight back in — an infinite loop printing nothing. It now reads the
position out and takes a move pair back, which guarantees progress because the
stack can only shrink.

Explicitly not attempted: dictating the whole position to re-sync. Long,
error-prone, and frustrating exactly when frustration is already high.

---

## 10. Speech in — Vosk

Vosk accepts a **grammar**, rebuilt each turn from the legal moves. It is
structurally impossible for the recogniser to return a move that cannot be
played. An open-vocabulary model cannot offer that, and its most dangerous
output is a confident transcription of a plausible wrong move.

**[r2] `[unk]` is in every grammar.** Without it the recogniser must return
*something* from the list, and a cough becomes a move.

**[r2] Control words are checked before any move parsing**, and a test asserts
that no control word also parses as a legal move. A collision would make one of
the two unreachable, and which one would depend on the position.

**[r2] Every grammar phrasing must parse back to its own move.** A test walks
every legal move in the opening position and round-trips every phrasing offered
for it. A grammar entry the parser then rejects is the worst possible failure:
the child says exactly what she was told to say and is told it wasn't
understood.

Echo handling: gate on `body.speaking`, empty the queue, RMS VAD.

**[r2] Capture must be callback-driven, and results must be collected when
ready.** Two bugs made the recogniser appear simply not to work:

- The read loop skipped any block PortAudio flagged as overflowed. Overflow
  happens on nearly every iteration once recognition runs inside the loop, so
  almost all the audio was discarded. A callback pushing into a queue decouples
  capture from recognition and drops nothing.
- `AcceptWaveform` returns True when Vosk has finalised an utterance, and the
  recogniser resets at that point. The return value was ignored, so
  `FinalResult()` at the end returned only the fragment after the reset --
  usually empty.

**[r2] A closed grammar needs every word to be in the model's lexicon.** An
unknown word is not an error Vosk raises; it logs to its C stderr and carries
on, so the grammar builds, recognition runs, and nothing ever matches. Single
letters are the live risk, since a grammar of "e four" and "b five" depends on
the model knowing "e" and "b" as words. `listener.missing_words()` swaps file
descriptor 2 to capture that log, and `tools/check_speech.py` reports it.

### 10.1 Parsing

Ported, including the number-homophone table and the ambiguous/unrecognised
distinction. Ambiguous asks which piece. Unrecognised asks again. Illegal
explains the rule.

**[r2] Three parsing bugs worth recording**, all found by tests:

- `board.attacks()` on a pawn returns its *capture diagonals*, so b2 appears to
  attack a3 and a simple push looks like it has two possible origins. Pawns
  must be selected by file.
- `"" in FILES` is `True`, because an empty string is a substring of anything.
  This crashed origin reconstruction on any SAN move without a disambiguator.
- Sliding pieces aimed along a blocked line are *blocked*, not incapable, and
  `attacks()` already stops at the blocker — so this needs checking against the
  unobstructed ray or the explanation degrades to a useless generic one.

**[r2] Promotion defaults to a queen.** "e eight" with a pawn on e7 is complete
and unambiguous to a child but incomplete as notation. Underpromotion stays
reachable by naming the piece.

---

## 11. Testing

`ohbot` and `sounddevice` are replaced in `sys.modules` before any package
import. The fake **records every motor command** rather than merely silencing
it, which is the assertion surface for the behaviours that actually break.

Engine and coach behaviour is tested against a **real Stockfish**. A stub can
confirm the code calls the engine; it cannot catch a sign error in centipawn
loss.

**[r2] Assert against phrase banks, not against chosen wordings.** Selection
rotates deterministically, so pinning one line makes a test fail when the bank
is reordered — which is not a behaviour change.

**[r2] Don't compare two engine calls for equality.** Stockfish carries its
hash table between analyses, so the same question asked twice in one process
can legitimately give two different best moves. Assert on the sampler instead.

Current state: 191 tests, ~12s, 85% coverage, no robot, no microphone, no audio
device. `ruff` and `mypy --disallow-untyped-defs` both clean.

---

## 12. Dependencies

`chess`, `ohbot`, `pyserial`, `numpy`, `sounddevice`, `vosk`,
`piper-tts>=1.3` (see §8). Stockfish is a system binary. `onnxruntime` no
longer needs listing — it is bundled in the Piper wheel from 1.3.0.

No `requests`, no `opencv-python`, no Ollama, no transformers.

Python 3.11 or 3.12. Not 3.14 — that caused build friction on this stack before.

---

## 13. Open decisions

1. ~~**Licence.**~~ **Settled: GPL-3.0-or-later.** `python-chess` is
   GPL-3.0-or-later and is imported, so the distributed combination is a
   derivative work. Stockfish is GPL-3.0 but invoked as a separate binary over
   UCI and carries no obligation. **The same analysis applies to
   `reachy_chess`, which imports python-chess identically and should be
   licensed to match before it goes public.**
2. **Head roll and Illuminating Eyes.** Handled in code either way (§7.3, §7.4);
   `tools/bringup.py` reports which you have and prints the flags.
3. **Gaze calibration.** Interface shipped; the mapping and
   `tools/calibrate_gaze.py` are written but unverified against real hardware.

---

## 14. Deliberately deferred

- Vision cross-check, if a camera is fitted later. Move confirmation sits
  behind a seam that currently always returns "unknown".
- Persistence across sessions — remembering a player and their progress.
- Two-robot play.
- Puzzle mode.
