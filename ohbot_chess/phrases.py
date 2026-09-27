# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Everything the robot can say.

Human-authored, reviewed, and version-controlled. There is no language model in
this application and this file is the reason it doesn't need one: a curated
bank cannot hallucinate a move that wasn't played, cannot get chess wrong, and
cannot take half a second to think of a word.

SELECTION IS DETERMINISTIC. Given the same game state, the same phrase comes
out. Random selection makes a demo impossible to debug -- you can never tell
whether you changed the behaviour or just got a different roll -- and the
variety it buys is worth less than the reproducibility it costs.

Placeholders are filled with str.format, so every phrase in a category must
accept the same keys.
"""

from __future__ import annotations

from . import config

# -- the robot's own moves --------------------------------------------------

ANNOUNCE = [
    "I'll play {move}.",
    "My move is {move}.",
    "I'm going {move}.",
    "Let's try {move}.",
]

ANNOUNCE_CAPTURE = [
    "I'll take it. {move}.",
    "I'm capturing. {move}.",
    "{move}. Sorry about that one.",
]

ANNOUNCE_CHECK = [
    "{move}. That's check.",
    "{move}. Check to your king.",
]

ANNOUNCE_CASTLE = [
    "I'm castling. {move}.",
    "Time to tuck my king away. {move}.",
]

ANNOUNCE_PROMOTE = [
    "My pawn made it. {move}.",
    "{move}. That pawn has been promoted.",
]

# Asking for the move to be made on the physical board. This is the point where
# the robot depends entirely on someone else's hands.
ASK_TO_MOVE = [
    "Can you move that one for me?",
    "Would you move it for me?",
    "Over to you to move it.",
]

# Said only after a genuinely patient wait. Impatience here was a real bug on
# the previous build: it asked while a hand was still over the board.
NUDGE = [
    "Have you had a chance to move my piece?",
    "Let me know when you've moved it.",
    "No rush. Tell me when it's done.",
]

REPEAT = [
    "I said {move}.",
    "My move was {move}.",
]

# Said when told its move cannot be played on the physical board. The robot is
# wrong here, and the tone should reflect that -- no defensiveness, no asking
# the person to check again, just take it back and try something else.
TRY_ANOTHER = [
    "Sorry, my mistake. Let me pick a different move.",
    "Ah, sorry. I'll try something else.",
    "My mistake. Let me think again.",
]

# Every candidate has been refused. Two boards that disagree about one piece
# can be recovered from by guessing again; this many refusals means they
# disagree about several, and guessing is wasting the person's time.
# Told a move was impossible after the fact, on the person's own turn.
REWIND = [
    "Sorry about that. I've taken us back a move -- let's try again from here.",
    "My mistake. We're back a move, so go again when you're ready.",
]

NOTHING_TO_REWIND = [
    "Sorry. There's nothing for me to take back yet, so let's carry on.",
]

OUT_OF_IDEAS = [
    "I think my board and your board have got out of step. Let me read out "
    "what I have, and you can tell me what's different.",
    "Something's not matching up between us. Here's the position I think we're in.",
]

# -- the child's turn -------------------------------------------------------

YOUR_TURN = [
    "Your turn.",
    "Your move.",
    "Off you go.",
    "What are you going to do?",
]

CONFIRM = [
    "{move}. Good.",
    "{move}.",
    "Right, {move}.",
]

# -- coaching ---------------------------------------------------------------
#
# The bands come from config. Tone matters more here than anywhere else in the
# file: this is a beginner being told they got something wrong, and the
# difference between "that was a blunder" and "careful, that leaves something
# hanging" is the difference between a lesson and a knock.

COACHING = {
    config.GREAT: [
        "That's the best move there. Well spotted.",
        "That's exactly it. Nice.",
        "That's the strongest move on the board.",
    ],
    config.GOOD: [
        "That's a solid move.",
        "Good, that works well.",
    ],
    config.INACCURACY: [
        "That's playable. {best} was a bit sharper.",
        "Not bad. I'd have looked at {best}.",
    ],
    config.MISTAKE: [
        "Careful, that lets me do something. {best} was safer.",
        "Hmm, that gives me a chance. Have a look at {best} next time.",
    ],
    config.BLUNDER: [
        "Careful. That leaves something for me. {best} would have held.",
        "Oh, watch out. I can take advantage of that one. {best} was the move.",
        "That one costs you something. {best} would have been safer.",
    ],
}

MISSED_MATE = [
    "You had a checkmate there. Have a look for it next time.",
    "There was a mate in that position. Worth hunting for.",
]

# -- input problems ---------------------------------------------------------

ILLEGAL = [
    "You can't quite do that, because {reason}.",
    "That one won't work, {reason}.",
    "Not that one, {reason}.",
]

AMBIGUOUS = [
    "Which {piece}? The one on {options}?",
    "I've got more than one {piece} that can go there. The one on {options}?",
]

NOT_UNDERSTOOD = [
    "Sorry, I didn't catch that. Can you say it again?",
    "I missed that one. Could you say it once more?",
    "I didn't quite hear. Try again?",
]

FALLBACK_TO_KEYBOARD = [
    "I'm having trouble hearing. You can type it instead.",
]

# -- game lifecycle ---------------------------------------------------------

GREETING = [
    "Hello. Shall we play some chess?",
    "Hello there. Ready for a game?",
]

EXPLAIN_ROLE = [
    "I can't reach the board, so I'll tell you my moves and you can move the "
    "pieces for both of us.",
    "I have no hands, so you'll be moving the pieces. I'll tell you what I want to play.",
]

GAME_START = [
    "You're playing {colour}. {first}",
    "You have the {colour} pieces. {first}",
]

CHECK_WARNING = [
    "That's check. Your king needs help.",
    "Careful, your king is in check.",
]

CHILD_WINS = [
    "That's checkmate. You've beaten me. Well played.",
    "Checkmate. You win. That was a good game.",
]

ROBOT_WINS = [
    "That's checkmate. Good game though, you made me work.",
    "Checkmate. Thank you for the game.",
]

STALEMATE = [
    "That's stalemate. Nobody wins. It's a draw.",
    "Stalemate. No legal moves left, so it's a draw.",
]

DRAW = [
    "That's a draw.",
    "This one's a draw.",
]

RESIGN = [
    "That's fine. Good game.",
    "No problem. Thanks for playing.",
]

GOODBYE = [
    "Thanks for the game. See you next time.",
    "That was fun. Goodbye.",
]

# -- board recovery ---------------------------------------------------------

BOARD_INTRO = [
    "Here's the position as I have it.",
    "This is what I think the board looks like.",
]

UNDO = [
    "Alright, taking back {moves}. Put those pieces back where they were.",
    "Undoing {moves}. Move those back for me.",
]

NOTHING_TO_UNDO = [
    "There's nothing to take back yet.",
]

HELP = [
    "Say a move like e four, or knight to f three. You can also say board to "
    "hear the position, or take that back to undo. If I ask for a move you "
    "can't play, say that's not legal and I'll try a different one.",
]

# Said while waiting for a piece to be moved, when the reply was not
# understood. Unrecognised words used to be taken as confirmation, which
# silently swallowed every protest.
NOT_UNDERSTOOD_WAITING = [
    "Sorry, I didn't catch that. Say done when you've moved it, or that's not legal if you can't.",
    "I missed that. Tell me done when it's moved, or that's not legal if I've "
    "asked for something impossible.",
]


# -- selection --------------------------------------------------------------


def pick(bank: list[str], seed: int = 0, **kwargs: object) -> str:
    """Choose deterministically from a bank and fill in the placeholders.

    `seed` should be something that varies across the game but is reproducible
    within it -- the move number is ideal. Rotating rather than sampling means
    the same game always sounds the same, and that a repeated situation two
    moves later doesn't repeat the same words.
    """
    if not bank:
        return ""
    phrase = bank[seed % len(bank)]
    try:
        return phrase.format(**kwargs)
    except (KeyError, IndexError):
        # A phrase missing a placeholder should not take the game down. Return
        # it unfilled rather than crashing mid-move.
        return phrase


def coaching(label: str, seed: int = 0, best: str = "") -> str:
    """A coaching line for a judgement label."""
    bank = COACHING.get(label, [])
    if not bank:
        return ""
    return pick(bank, seed, best=best)


def join_options(options: list[str]) -> str:
    """'Nbd2, Nfd2' -> 'N b d two or N f d two' for reading aloud."""
    if not options:
        return ""
    if len(options) == 1:
        return options[0]
    return ", ".join(options[:-1]) + " or " + options[-1]
