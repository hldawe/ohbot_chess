# ohbot_chess

Chess with an Ohbot. It has no hands, so **you move the pieces** — for both of you.

Ohbot works out its move, tells you what it wants to play, and waits while you
make it happen on a real board. You reply by speaking or typing. It watches
your face, not the board.

Everything runs **locally**: Stockfish, Vosk and Piper are all on your machine.
No API keys, no internet, nothing leaves the laptop.

```bash
python -m ohbot_chess.cli --teach --speech --vosk-model ./model
```

Or, with nothing installed and no robot on the desk:

```bash
python -m ohbot_chess.cli --mock --teach
```

**[Setup](#setup)** · **[Play](#play)** · **[What you can say](#what-you-can-say-at-any-time)**

## Setup

Nine steps. Steps 1–5 get you a game in the terminal; 6–8 add the robot and its
voice. Nothing here needs an internet connection once it's done.

Everything is downloaded once and lives inside the project folder, so removing
the folder removes the lot.

### 1. Python 3.11 or 3.12

Not 3.13 or 3.14 — the audio and ONNX wheels lag behind, and this stack has
caused build friction there before.

```bash
python3 --version          # check what you have
```

If you need a specific version, [`uv`](https://docs.astral.sh/uv/) will fetch
one for you in the next step without touching your system Python.

### 2. Get the code and make a virtual environment

```bash
git clone <your-repo-url> ohbot_chess
cd ohbot_chess

uv venv --python 3.11 && source .venv/bin/activate
# or, without uv:
#   python3.11 -m venv .venv && source .venv/bin/activate
```

On Windows the activate line is `.venv\Scripts\activate`.

### 3. Install the Python dependencies

Check first that every pin has something that will actually install on your
machine. It takes a couple of seconds and needs nothing installed:

```bash
python tools/check_requirements.py
```

Then:

```bash
uv pip install -r requirements.txt
# or: pip install -r requirements.txt
```

Two of the pins are deliberately **not** the newest release. Both look like
mistakes and both are explained in `requirements.txt`, so please read it before
bumping either.

> **`vosk` is pinned to 0.3.44, not 0.3.45.** Release 0.3.45 ships wheels for
> Linux, ARM and Windows only — it has **no macOS wheel of any kind**. On a Mac
> pip reports this as though the version does not exist:
>
> ```
> ERROR: Could not find a version that satisfies the requirement vosk==0.3.45
> (from versions: 0.3.38, ..., 0.3.44)
> ```
>
> It does exist. pip simply cannot see it from macOS. 0.3.44 has wheels for
> every platform and is the right pin everywhere.

> **`numpy` is pinned below 2.5** because numpy 2.5 and later require Python
> 3.12, and this project supports 3.11 as well. If you see pip mention
> "Ignored the following versions that require a different python version",
> that is this, and it is harmless.

> **`piper-tts` must be 1.3.0 or newer.** Versions 1.1 and 1.2 depend on a
> separate `piper-phonemize` package that has **no macOS wheel**, so
> `pip install piper-tts` fails outright on a Mac with `ResolutionImpossible`.
> From 1.3.0 espeak-ng is embedded and the dependency is gone. `piper-tts`
> pulls in `onnxruntime` itself, so that is not listed separately.

### 4. Install Stockfish

A system binary, not a Python package.

```bash
brew install stockfish              # macOS
sudo apt install stockfish          # Debian / Ubuntu
winget install Stockfish            # Windows
```

Check it's on your PATH:

```bash
stockfish --help | head -1          # should print a version line
```

If you'd rather not install it system-wide, download a binary from
[stockfishchess.org/download](https://stockfishchess.org/download/) and pass
`--stockfish /path/to/binary` to every command below.

### 5. Play a game with no robot

```bash
python -m ohbot_chess.cli --mock --teach
```

Type moves as `e4`, `Nf3` or `e2e4`. This runs the whole game — coaching, board
readback, the lot — with no hardware and no models. Worth doing before going
further, because everything after this point is about the robot rather than the
chess.

---

### 6. Connect the robot and find out what it has

Plug the Ohbot in over USB, then:

```bash
python tools/bringup.py
```

It moves every motor in turn, tries the head roll, flashes the eyes and speaks.
It then prints the exact flags to use. Two things it settles that the software
cannot settle alone:

- **Head roll.** Detection reads the library's motor table, but the table can be
  wrong, so bringup moves the servo and asks you what you saw.
- **Illuminating Eyes.** This **cannot be detected** — `setEyeColour` writes to
  the serial port with no readback, so a missing accessory looks exactly like a
  fitted one. Only your eyes can answer.

Then play, with whatever flags bringup printed:

```bash
python -m ohbot_chess.cli --teach --eyes     # example: eyes fitted, head roll detected
```

Typed moves for now — the voice comes next. See **[Play](#play)** for every flag.

### 7. Download the voice

Two files, about 63 MB together, into a `voices/` folder.

```bash
mkdir -p voices
curl -L -o voices/en_GB-alba-medium.onnx \
  'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium/en_GB-alba-medium.onnx'
curl -L -o voices/en_GB-alba-medium.onnx.json \
  'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium/en_GB-alba-medium.onnx.json'
```

`alba` is a Scottish voice — the same one the Reachy build uses, so the two
robots sound like one system. To hear the alternatives before committing, the
[samples page](https://rhasspy.github.io/piper-samples/) has every voice; swap
the name in **both** the path and the filename, and pass `--voice <name>`.

The `.onnx.json` is not optional. Piper needs both files, and a missing config
file gives a confusing error about the model rather than about the config.

### 8. Download the speech recogniser

About 40 MB, unzipped into `model/`.

```bash
curl -L -o vosk-model.zip \
  'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip'
unzip -q vosk-model.zip
mv vosk-model-small-en-us-0.15 model
rm vosk-model.zip
```

The small model is the right choice here and a bigger one is not an upgrade.
Accuracy on open vocabulary is irrelevant when the recogniser is constrained to
a per-turn grammar, and the larger models only add latency. There is no British
English Vosk model; the grammar makes that not matter.

If alphacephei.com is unreachable, there is a community mirror at
[huggingface.co/grimso/vosk-models](https://huggingface.co/grimso/vosk-models).

### 9. Check the whole voice path, then play

```bash
python tools/check_speech.py --vosk-model ./model
```

This tests four things in the order they fail: the voice file, the WAV format
the lip sync depends on, the microphone, and the constrained grammar. The last
step asks you to say an illegal move and shows it being refused *at the
recogniser* — worth watching once, because it's the reason for this design.

Then the real thing:

```bash
python -m ohbot_chess.cli --teach --speech --vosk-model ./model
```

That is the full command — see **[Play](#play)** for the shorter variants and
the complete flag list.

On macOS the first run will need microphone permission. If the terminal was
never granted it, the check reports digital silence rather than hanging:
**System Settings → Privacy & Security → Microphone**, enable your terminal,
then restart it.

### Optional: teach it where the board is

```bash
python tools/calibrate_gaze.py
```

Drive the eyes to two opposite corners with `w`/`a`/`s`/`d` and press enter at
each. Ohbot will then look at the square it's naming as it names it.

Entirely optional — uncalibrated it just looks down at the board, which is what
the Reachy build always did. If the printed square positions look wrong,
**delete `gaze_calibration.json`**: looking at the board in general is much
better than confidently looking at the wrong square.

### What you should have

```text
ohbot_chess/
  .venv/
  voices/
    en_GB-alba-medium.onnx
    en_GB-alba-medium.onnx.json
  model/                       (the unzipped Vosk model)
  gaze_calibration.json        (only if you ran the calibration)
```

`voices/`, `model/` and `gaze_calibration.json` are all git-ignored.

### If something goes wrong

| Symptom | Cause |
| --- | --- |
| `No matching distribution found for vosk` | you bumped vosk to 0.3.45, which has no macOS wheel — see step 3 |
| `Ignored the following versions that require a different python version` | numpy 2.5+ needs Python 3.12; harmless, the pin handles it |
| `ResolutionImpossible`, `piper-phonemize` | `piper-tts` older than 1.3.0 — see step 3 |
| `Could not start Stockfish` | not on PATH; use `--stockfish /full/path` |
| `Missing Piper voice files` | wrong folder, or only one of the two files downloaded |
| `Could not load the Vosk model` | pass the unzipped **directory**, not the zip |
| Microphone "returned pure silence" | OS permission, not a code problem — see step 9 |
| It talks but the mouth doesn't move | the WAV isn't 16-bit mono; run `tools/check_speech.py` |
| Speech recognition hears nothing at all | run `python tools/check_speech.py --vosk-model ./model` — step 4 reports whether the model knows the words the grammar is built from |
| It asks for a move you can't play | say `that's not legal` — see [below](#when-it-asks-for-an-impossible-move) |
| Robot is silent | Ohbot has no speaker — audio plays through your laptop |

## Play

Copy the line you want. Every one of these is complete and will run as-is.

### Difficulty

Easiest to hardest. `cub` is the default.

```bash
python -m ohbot_chess.cli --level kitten --teach    # 1st, easiest
python -m ohbot_chess.cli --level cub --teach       # 2nd
python -m ohbot_chess.cli --level fox --teach       # 3rd
python -m ohbot_chess.cli --level owl --teach       # 4th
python -m ohbot_chess.cli --level sharp --teach     # 5th, full strength
```

| Level | What it's like |
| --- | --- |
| `kitten` | very gentle, misses things on purpose |
| `cub` | gentle, but punishes a free piece |
| `fox` | plays properly most of the time |
| `owl` | strong, rarely gives anything away |
| `sharp` | full strength, not for a first game |

### Typing or speaking

The lines above use the keyboard. To speak your moves instead, add
`--speech --vosk-model ./model`:

```bash
python -m ohbot_chess.cli --level cub --teach --speech --vosk-model ./model
```

### With or without coaching

`--teach` makes it comment on your moves. Leave it off for a plain game:

```bash
python -m ohbot_chess.cli --level cub                       # no coaching
python -m ohbot_chess.cli --level cub --teach               # with coaching
```

### No robot

Runs the whole game in the terminal. Needs nothing installed beyond step 3 —
no robot, no voice files, no microphone:

```bash
python -m ohbot_chess.cli --mock --teach
python -m ohbot_chess.cli --mock --teach --level kitten
```

### Playing black

You play white by default and go first. To play black and let Ohbot open:

```bash
python -m ohbot_chess.cli --level cub --teach --child-plays black
```

### Your robot's hardware

Add whatever `tools/bringup.py` told you. These are the only two that matter:

```bash
python -m ohbot_chess.cli --level cub --teach --eyes            # eyes fitted
python -m ohbot_chess.cli --level cub --teach --headroll no     # no head roll
```

### The one to use most of the time

Everything on, spoken moves, gentle opponent:

```bash
python -m ohbot_chess.cli --level cub --teach --speech --vosk-model ./model --eyes
```

### If Stockfish isn't on your PATH

Add `--stockfish` with the full path to any of the above:

```bash
python -m ohbot_chess.cli --level cub --teach --stockfish /opt/homebrew/bin/stockfish
```

### Every flag

| Flag | Default | What it does |
| --- | --- | --- |
| `--level` | `cub` | `kitten`, `cub`, `fox`, `owl`, `sharp` |
| `--teach` | off | comment on your moves |
| `--speech` | off | listen for spoken moves |
| `--vosk-model` | `model` | path to the unzipped Vosk directory |
| `--child-plays` | `white` | which colour you play |
| `--mock` | off | run with no robot at all |
| `--eyes` | off | the Illuminating Eyes accessory is fitted |
| `--headroll` | `auto` | `yes` / `no` to override detection |
| `--stockfish` | `stockfish` | path to the binary, if not on PATH |
| `--voice` | `en_GB-alba-medium` | Piper voice name |
| `--voice-dir` | `voices` | where the `.onnx` pair lives |
| `--no-tts` | off | use the robot's built-in voice instead of Piper |
| `--gaze-calibration` | `gaze_calibration.json` | board corners, if calibrated |
| `--analysis-depth` | 14 | coaching strength, independent of `--level` |
| `--seed` | none | reproducible move choice, for debugging |
| `--no-board` | off | don't print the board after each move |
| `--ascii` | off | letters instead of chess glyphs |
| `--no-log` | off | don't write a game log |
| `--log-dir` | `logs` | where game logs go |
| `--no-mercy` | off | don't ease off when the game is already lost |
| `--no-idle` | off | disable blinking and idle motion |
| `--mic` | system default | input device index |

`python -m ohbot_chess.cli --help` lists the lot.

### How it hears you

The recogniser is given a **grammar rebuilt from the legal moves every turn**.
It is not allowed to return anything else. So "knight" cannot come back as
"night", and an illegal move is refused at the recogniser rather than at the
parser.

That is the whole reason this uses Vosk rather than an open-vocabulary model.
An open model's most dangerous output is a confident transcription of a
plausible wrong move, and a closed grammar makes that impossible rather than
merely unlikely.

Natural phrasings work: *"e four"*, *"e two e four"*, *"knight to f three"*,
*"bishop c four"*, *"castle kingside"*, *"queen takes e five"*.

### What you can say at any time

| Say | What happens |
| --- | --- |
| `again` / `repeat` | re-announces Ohbot's move |
| `show` | prints the board in the terminal |
| `fix` | opens the position editor (see below) |
| **`that's not legal`** | **Ohbot has asked for a move you can't play — it withdraws it and picks another** |
| `board` | reads the whole position aloud |
| `take that back` | undoes a full move pair |
| `done` / `moved it` | tells it you've moved its piece |
| `help` | lists these |
| `resign` / `stop` | ends the game |

### When it asks for an impossible move

Ohbot cannot see the board. If the two boards drift apart — a piece knocked
over, a move made differently from the one announced — it will eventually ask
for something you cannot play. Its move is legal in the position *it* thinks
you are in.

Say **`that's not legal`** (or `illegal`, `can't do that`, `try another`). It
takes the move back, apologises, and picks a different one, and it will not
offer that move again this turn.

If you refuse several in a row it stops guessing, reads the whole position out
so you can find the difference, and takes a move pair back so you can replay
from somewhere you both agree on.

Saying it on your own turn works too — that's for when you've walked to the
board, found you can't make its move, and come back. It rewinds a pair.

## How the difficulty works

The commands are under [Difficulty](#difficulty). This is what is going on
underneath.

Levels weaken the engine by **sampling a worse move from a full-strength
candidate list**, not by limiting search depth. A depth-limited engine blunders
tactically while still crushing you positionally, which plays like nothing
human and teaches nothing.

The **coach is never weakened**. `--analysis-depth` is independent of `--level`,
so the opponent can be a kitten while the teacher is not. On battery-powered
hardware those two competed for one CPU budget; tethered to a laptop they don't.

Losing badly triggers **mercy**: the engine quietly eases off. It never says so.

## When the boards disagree

Ohbot cannot see the pieces, so its idea of the position can drift from yours.
Four things help.

**The board is printed after every move**, from your side, with the last move
highlighted and the FEN underneath. `--no-board` turns it off; `--ascii` uses
letters if chess glyphs render badly in your terminal.

**Every move names both squares.** "knight on g one to f three", not "knight to
f three" — so you can check it against the real board as you hear it, rather
than discovering a mismatch five moves later. Castling names the rook as well
as the king; en passant tells you which pawn comes off; promotion tells you to
swap the piece.

**`fix` opens a position editor.**

```
set e4 white knight     put a piece on a square  (also: set e4 wn, set e4 N)
clear e4                take a piece off
move e4 f6              relocate, no legality check
turn white              whose move it is
castling KQkq           set rights directly ('-' for none)
fen <string>            replace the whole position
reset / show / undo / done / cancel
```

It refuses to hand back an impossible position and tells you which rule is
broken. Note that **editing clears the move history**, so `take that back`
won't reach past an edit — it says so when you finish.

**Every game is logged**, to `logs/` by default. Two files: a `.pgn` you can
open in any chess tool, and a `.jsonl` recording what was heard, what it parsed
to, and the position after each move. That pairing is the point — a move that
is legal, in the game, and *wrong* is invisible in a PGN, but here it sits next
to the words that produced it. `--no-log` turns it off.

If a game goes wrong, the `.jsonl` is the thing to keep.

## The board

There is no camera, so Ohbot cannot see the pieces. If the real board and its
internal one drift apart, say **`board`** and it will read out the position it
thinks you're playing. **`take that back`** covers the commonest cause — a piece
knocked over, or a move changed halfway through.

`--gaze-calibration` is optional. Run `tools/calibrate_gaze.py` and Ohbot will
look at the square it's naming as it names it. Uncalibrated it just looks down
at the board, which is fine. If the calibration looks off, delete the file:
confidently looking at the wrong square is much worse than not trying.

## Known limitations

**The voice does not come from the head.** Ohbot has no speaker; audio plays
through your laptop. Lip sync still runs, so the mouth moves in time, and that
is usually enough to localise the voice to the face — but it works much better
if the robot is sitting *next to* the laptop rather than across the desk. This
is accepted rather than solved.

**No vision.** The camera is an optional accessory and v1 doesn't use one. The
interface leaves room for it.

**It cannot check you moved the piece correctly.** It trusts you. That's the
deal.

## Development

Using it as a library rather than through the CLI:

```python
from ohbot_chess import GameState, Engine, Presenter, Game, KeyboardInput
from ohbot_chess.body import OhbotBody

state = GameState("white")
with Engine("stockfish") as engine, OhbotBody() as body:
    Game(state, engine, Presenter(body), KeyboardInput()).play()
```

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                     # ~12s, no robot, no microphone, no audio device
ruff check . && mypy ohbot_chess
```

The suite replaces `ohbot` and `sounddevice` in `sys.modules` before anything
is imported, so it runs anywhere. The fake **records every motor command**
rather than merely silencing it, which is what lets the tests assert on the
things that actually break: the mouth being driven while lip sync owns it, the
head failing to recentre, head-roll keyframes on a robot with no head-roll
servo, and gestures failing to overlap speech.

Engine and coach behaviour is tested against a **real Stockfish**, because a
stub can only confirm the code calls the engine — it cannot catch a sign error
in centipawn loss, which is the bug this code was most likely to have and did.

## Layout

```text
ohbot_chess/
  chess_core.py    GameState, Engine, Coach — pure chess, no robot
  moves.py         parsing, spoken normalisation, illegal-move explanations
  expression.py    poses, gestures, gaze — imports no robot library at all
  body.py          Body protocol, MockBody, OhbotBody — the only hardware file
  presentation.py  chess events -> faces and words
  phrases.py       everything it can say, human-authored
  listener.py      Vosk, per-turn grammar
  speech.py        Piper
  game.py          the turn loop
tools/             bringup, gaze calibration, speech check
docs/SPEC.md       the design, and why
```

`body.py` knows about servos but not chess. `presentation.py` knows about chess
but not servos. They change for different reasons — library churn versus
coaching tone — so neither forces an edit to the other.

## Licence

**GPL-3.0-or-later.** See [LICENSE](LICENSE) for the full text and
[NOTICE](NOTICE) for third-party components.

This project imports python-chess, which is GPL-3.0-or-later, so what is
distributed here is a derivative work and carries the same terms. Stockfish is
also GPL-3.0 but runs as a separate binary over UCI — running a program is not
linking to it — so it imposes no obligation on this code.
