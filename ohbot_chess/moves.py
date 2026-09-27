# ohbot_chess -- chess with a robot that has no hands.
# Copyright (C) 2026 Heather Dawe
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning what a person said or typed into a legal move -- or into a useful
answer about why it isn't one.

Three outcomes matter and they are NOT the same thing:

    move          we know exactly what was meant
    ambiguous     we know what was meant but not which piece -- ASK
    illegal       a real move that cannot be played here -- EXPLAIN
    unknown       we didn't understand -- ask again

Collapsing ambiguous into unknown was a bug on the previous build: the child
says "knight to f three" with two knights able to reach f3, and being told
"sorry, I didn't catch that" is both wrong and discouraging. She was perfectly
clear; the position was ambiguous.

Speech recognition arrives here already constrained by a per-turn grammar (see
listener.py), so most of the mishearing this module handles is within-grammar
confusion -- rank numbers above all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import chess

# -- outcome kinds ----------------------------------------------------------

MOVE = "move"
AMBIGUOUS = "ambiguous"
ILLEGAL = "illegal"
UNKNOWN = "unknown"


@dataclass
class Parsed:
    kind: str
    move: chess.Move | None = None
    candidates: list[chess.Move] = field(default_factory=list)
    reason: str = ""
    normalised: str = ""

    @property
    def ok(self) -> bool:
        return self.kind == MOVE


# -- spoken normalisation ---------------------------------------------------

FILES = "abcdefgh"

# How a recogniser renders spoken file letters.
FILE_WORDS = {
    "a": "a",
    "ay": "a",
    "eh": "a",
    "b": "b",
    "bee": "b",
    "be": "b",
    "c": "c",
    "see": "c",
    "sea": "c",
    "si": "c",
    "d": "d",
    "dee": "d",
    "e": "e",
    "ee": "e",
    "f": "f",
    "ef": "f",
    "eff": "f",
    "g": "g",
    "gee": "g",
    "jee": "g",
    "h": "h",
    "aitch": "h",
    "haitch": "h",
    "age": "h",
}

# Plain number words.
NUMBERS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
}

# Words that are ONLY numbers when they follow a file letter. "knight to f
# three" must keep its preposition; "e to e four" must become e2e4. Context is
# the whole difference, so these are applied positionally, never globally.
NUMBER_HOMOPHONES = {
    "to": "2",
    "too": "2",
    "for": "4",
    "fore": "4",
    "ate": "8",
    "eight": "8",
    "won": "1",
    "one": "1",
    "free": "3",
    "tree": "3",
    "three": "3",
    "sicks": "6",
    "sics": "6",
    "six": "6",
    "sever": "7",
    "seven": "7",
    "fife": "5",
    "five": "5",
}

PIECE_WORDS = {
    "king": "K",
    "queen": "Q",
    "rook": "R",
    "rock": "R",
    "castle": "R",
    "tower": "R",
    "bishop": "B",
    "bish": "B",
    "knight": "N",
    "night": "N",
    "horse": "N",
    "pony": "N",
    "pawn": "P",
    "porn": "P",
    "prawn": "P",
}

CAPTURE_WORDS = {"takes", "take", "captures", "capture", "x", "times", "eats"}

CASTLE_KINGSIDE = {
    "castle kingside",
    "castles kingside",
    "king side castle",
    "short castle",
    "castle short",
    "castle king side",
    "o o",
    "0 0",
}
CASTLE_QUEENSIDE = {
    "castle queenside",
    "castles queenside",
    "queen side castle",
    "long castle",
    "castle long",
    "castle queen side",
    "o o o",
    "0 0 0",
}

_PUNCT = re.compile(r"[^\w\s+#-]")
_SPACES = re.compile(r"\s+")
_SQUARE = re.compile(r"^[a-h][1-8]$")


def normalise_spoken(text: str) -> str:
    """Turn a spoken utterance into something parseable.

    Word-by-word rather than by regex over the whole string, because the
    number-homophone rule needs to know what the PREVIOUS token was.
    """
    cleaned = _PUNCT.sub(" ", (text or "").lower())
    cleaned = _SPACES.sub(" ", cleaned).strip()
    if not cleaned:
        return ""

    # Castling is a fixed phrase; handle it before tokenising.
    for phrase in CASTLE_KINGSIDE:
        if phrase in cleaned:
            return "O-O"
    for phrase in CASTLE_QUEENSIDE:
        if phrase in cleaned:
            return "O-O-O"

    tokens = cleaned.split()
    out: list[str] = []
    prev_was_file = False

    for token in tokens:
        # An already-formed square ("e4") passes straight through.
        if _SQUARE.match(token):
            out.append(token)
            prev_was_file = False
            continue

        if token in PIECE_WORDS:
            out.append(PIECE_WORDS[token])
            prev_was_file = False
            continue

        if token in CAPTURE_WORDS:
            out.append("x")
            prev_was_file = False
            continue

        if token in FILE_WORDS:
            out.append(FILE_WORDS[token])
            prev_was_file = True
            continue

        # The positional rule: after a file letter, ambiguous words are ranks.
        if prev_was_file and token in NUMBER_HOMOPHONES:
            out.append(NUMBER_HOMOPHONES[token])
            prev_was_file = False
            continue

        if token in NUMBERS:
            out.append(NUMBERS[token])
            prev_was_file = False
            continue

        if token.isdigit():
            out.append(token)
            prev_was_file = False
            continue

        # Anything else -- "to", "moves", "please" -- is filler between the
        # parts that matter, and dropping it is safer than guessing at it.
        prev_was_file = False

    return _glue_squares(out)


def _glue_squares(tokens: list[str]) -> str:
    """Join adjacent file+rank tokens into squares: ['e','4'] -> ['e4']."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if (
            len(token) == 1
            and token in FILES
            and i + 1 < len(tokens)
            and tokens[i + 1] in "12345678"
            and len(tokens[i + 1]) == 1
        ):
            out.append(token + tokens[i + 1])
            i += 2
            continue
        out.append(token)
        i += 1
    return " ".join(out)


# -- parsing ----------------------------------------------------------------


def parse(text: str, board: chess.Board) -> Parsed:
    """Interpret text as a move in this position.

    Tries strict notation first, because a typed "Nf3" should not go anywhere
    near the spoken-language path. Falls back to a tolerant token match that
    handles speech, coordinates and half-remembered notation alike.
    """
    raw = (text or "").strip()
    if not raw:
        return Parsed(UNKNOWN, normalised="")

    # 1. Exact SAN, as typed by someone who knows the notation.
    strict = _try_san(raw, board)
    if strict is not None:
        return strict

    # 2. Exact UCI, e.g. "g1f3", "e7e8q".
    uci = _try_uci(raw, board)
    if uci is not None:
        return uci

    # 3. Everything else: normalise and match against legal moves.
    normalised = normalise_spoken(raw)
    if not normalised:
        return Parsed(UNKNOWN, normalised="")

    # Normalisation may itself have produced valid notation.
    for attempt in (_try_san(normalised, board), _try_uci(normalised, board)):
        if attempt is not None:
            attempt.normalised = normalised
            return attempt

    return _match_tokens(normalised, board)


def _default_promotion(move: chess.Move, board: chess.Board) -> chess.Move | None:
    """Fill in a missing promotion piece with a queen.

    "e eight" with a pawn on e7 is complete and unambiguous to a child, but
    incomplete as notation -- python-chess rejects it. Underpromotion is real
    but rare, and it stays reachable by naming the piece ("e eight rook"), so
    defaulting to a queen costs nothing and removes a baffling rejection.
    """
    if move.promotion is not None:
        return None
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.PAWN:
        return None
    if chess.square_rank(move.to_square) not in (0, 7):
        return None
    queening = chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)
    return queening if queening in board.legal_moves else None


def _try_san(text: str, board: chess.Board) -> Parsed | None:
    """Parse strict SAN. Returns None if it isn't SAN at all."""
    candidate = text.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
    try:
        move = board.parse_san(candidate)
    except chess.AmbiguousMoveError:
        return Parsed(
            AMBIGUOUS,
            candidates=_ambiguous_candidates(candidate, board),
            normalised=candidate,
        )
    except chess.IllegalMoveError:
        return _explain_san_illegal(candidate, board)
    except (ValueError, AssertionError):
        return None
    return Parsed(MOVE, move=move, normalised=candidate)


def _try_uci(text: str, board: chess.Board) -> Parsed | None:
    compact = text.replace(" ", "").lower()
    if not re.fullmatch(r"[a-h][1-8][a-h][1-8][qrbn]?", compact):
        return None
    try:
        move = chess.Move.from_uci(compact)
    except ValueError:
        return None
    if move in board.legal_moves:
        return Parsed(MOVE, move=move, normalised=compact)
    queening = _default_promotion(move, board)
    if queening is not None:
        return Parsed(MOVE, move=queening, normalised=compact)
    return Parsed(ILLEGAL, move=move, normalised=compact)


_SAN_SHAPE = re.compile(r"^([KQRBN])?([a-h1-8]{0,2})x?([a-h][1-8])(?:=([QRBN]))?[+#]?$")


def _explain_san_illegal(text: str, board: chess.Board) -> Parsed:
    """Work out what an illegal-but-well-formed SAN move was trying to do.

    python-chess tells us the move is illegal but not which move was meant, and
    "that's not legal" without a reason teaches nothing. So the intended piece
    and destination are recovered from the notation, and the move reconstructed
    where a single candidate piece exists -- which is what explain_illegal
    needs in order to say something specific.
    """
    match = _SAN_SHAPE.match(text)
    if not match:
        return Parsed(ILLEGAL, normalised=text)

    piece_letter, _hint, square_name, promoted = match.groups()
    target = chess.parse_square(square_name)
    piece_type = chess.Piece.from_symbol(piece_letter).piece_type if piece_letter else chess.PAWN

    occupant = board.piece_at(target)
    if occupant is not None and occupant.color == board.turn:
        return Parsed(
            ILLEGAL,
            normalised=text,
            reason=(
                f"your own {chess.piece_name(occupant.piece_type)} is already "
                f"on {say_square(square_name)}"
            ),
        )

    # If exactly one of our pieces of that type could conceivably be the mover,
    # reconstruct the move so explain_illegal can reason about the board.
    #
    # Pawns are selected by FILE, not by attack set: board.attacks() on a pawn
    # returns its capture diagonals, so b2 "attacks" a3 and a plain push to a3
    # would look like it had two possible origins.
    candidates = list(board.pieces(piece_type, board.turn))
    if piece_type == chess.PAWN:
        # `"" in FILES` is True -- an empty string is a substring of anything --
        # so the truthiness check has to come first.
        hinted = _hint[:1]
        file_letter = hinted if (hinted and hinted in FILES) else square_name[0]
        wanted = chess.FILE_NAMES.index(file_letter)
        origins = [sq for sq in candidates if chess.square_file(sq) == wanted]
    else:
        origins = [sq for sq in candidates if target in board.attacks(sq)]
        if _hint:
            origins = [sq for sq in origins if _matches_hint(sq, _hint)]
    if len(origins) == 1:
        promotion = chess.Piece.from_symbol(promoted).piece_type if promoted else None
        rebuilt = chess.Move(origins[0], target, promotion=promotion)
        queening = _default_promotion(rebuilt, board)
        if queening is not None:
            return Parsed(MOVE, move=queening, normalised=text)
        return Parsed(ILLEGAL, move=rebuilt, normalised=text)

    # A bishop, rook or queen aimed along a line it cannot travel is blocked,
    # not incapable -- and "there's a piece in the way" is the useful thing to
    # say. board.attacks() already stops at the blocker, so this has to be
    # checked against the unobstructed ray instead.
    if piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        aligned = [sq for sq in candidates if chess.ray(sq, target)]
        blocked = [sq for sq in aligned if _path_blocked(board, sq, target)]
        if blocked:
            return Parsed(
                ILLEGAL,
                normalised=text,
                reason=(
                    f"there's a piece in the way, so the "
                    f"{chess.piece_name(piece_type)} can't get through"
                ),
            )

    return Parsed(
        ILLEGAL,
        normalised=text,
        reason=_no_piece_reason(piece_type, square_name, board),
    )


def _matches_hint(square: int, hint: str) -> bool:
    """Whether a square satisfies a SAN disambiguator like the 'b' in Nbd7."""
    name = chess.square_name(square)
    return all(char in name for char in hint)


def _ambiguous_candidates(text: str, board: chess.Board) -> list[chess.Move]:
    """Which legal moves a piece-and-destination phrase could have meant."""
    match = re.search(r"([KQRBN])?.*?([a-h][1-8])", text)
    if not match:
        return []
    piece_letter, square_name = match.group(1), match.group(2)
    target = chess.parse_square(square_name)
    piece_type = chess.Piece.from_symbol(piece_letter).piece_type if piece_letter else chess.PAWN
    return [
        m
        for m in board.legal_moves
        if m.to_square == target and (board.piece_type_at(m.from_square) == piece_type)
    ]


def resolve_clarification(
    text: str, candidates: list[chess.Move], board: chess.Board
) -> chess.Move | None:
    """Resolve a reply to "which piece?" against the candidates just offered.

    Without this the answer goes through the full parser, so a bare "b one"
    resolves nothing and the whole move has to be said again -- which is
    exactly the moment a person is least inclined to repeat themselves.

    Accepts an origin square ("b one", "b1"), a file letter, or a rank.
    """
    if not candidates:
        return None

    normalised = normalise_spoken(text) or (text or "").strip().lower()
    tokens = normalised.split()
    squares = [t for t in tokens if _SQUARE.match(t)]

    # A full origin square is unambiguous.
    for name in squares:
        target = chess.parse_square(name)
        for move in candidates:
            if move.from_square == target:
                return move

    # A bare file or rank, when it picks out exactly one candidate.
    for token in tokens:
        if len(token) != 1:
            continue
        if token in FILES:
            wanted = chess.FILE_NAMES.index(token)
            matches = [m for m in candidates if chess.square_file(m.from_square) == wanted]
        elif token in "12345678":
            wanted = int(token) - 1
            matches = [m for m in candidates if chess.square_rank(m.from_square) == wanted]
        else:
            continue
        if len(matches) == 1:
            return matches[0]

    return None


def _match_tokens(normalised: str, board: chess.Board) -> Parsed:
    """Tolerant match: pull out piece, squares and promotion, then filter."""
    tokens = normalised.split()

    if normalised in ("O-O", "O-O-O"):
        return _try_san(normalised, board) or Parsed(ILLEGAL, normalised=normalised)

    squares = [t for t in tokens if _SQUARE.match(t)]
    pieces = [t for t in tokens if t in "KQRBNP" and len(t) == 1]
    promotion = None
    if len(pieces) > 1 and squares:
        # "pawn e8 queen" -- last piece letter after a square is a promotion.
        promotion = chess.Piece.from_symbol(pieces[-1]).piece_type

    piece_type = None
    if pieces:
        symbol = pieces[0]
        piece_type = chess.Piece.from_symbol(symbol).piece_type

    if not squares:
        return Parsed(UNKNOWN, normalised=normalised)

    # Two squares: an explicit from-to, so no ambiguity is possible.
    if len(squares) >= 2:
        origin = chess.parse_square(squares[0])
        target = chess.parse_square(squares[-1])
        matches = [
            m for m in board.legal_moves if m.from_square == origin and m.to_square == target
        ]
        if matches:
            if promotion:
                promoted = [m for m in matches if m.promotion == promotion]
                if promoted:
                    return Parsed(MOVE, move=promoted[0], normalised=normalised)
            return Parsed(MOVE, move=matches[0], normalised=normalised)
        attempted = chess.Move(origin, target, promotion=promotion)
        queening = _default_promotion(attempted, board)
        if queening is not None:
            return Parsed(MOVE, move=queening, normalised=normalised)
        return Parsed(ILLEGAL, move=attempted, normalised=normalised)

    # One square: the destination. Narrow by piece type if we were told one.
    target = chess.parse_square(squares[0])
    matches = [m for m in board.legal_moves if m.to_square == target]
    if piece_type is not None:
        matches = [m for m in matches if board.piece_type_at(m.from_square) == piece_type]
    elif not pieces:
        # No piece named at all means a pawn move, exactly as in SAN.
        matches = [m for m in matches if board.piece_type_at(m.from_square) == chess.PAWN]

    if promotion:
        promoted = [m for m in matches if m.promotion == promotion]
        if promoted:
            matches = promoted

    if len(matches) == 1:
        return Parsed(MOVE, move=matches[0], normalised=normalised)
    if len(matches) > 1:
        # Promotion choices to the same square are not a real ambiguity for a
        # child -- default to a queen and let "rook" be said explicitly.
        promotions = {m.promotion for m in matches}
        if len(promotions) > 1 and None not in promotions:
            queen_moves = [m for m in matches if m.promotion == chess.QUEEN]
            if queen_moves:
                return Parsed(MOVE, move=queen_moves[0], normalised=normalised)
        return Parsed(AMBIGUOUS, candidates=matches, normalised=normalised)

    return Parsed(
        ILLEGAL,
        move=None,
        normalised=normalised,
        reason=_no_piece_reason(piece_type, squares[0], board),
    )


def _no_piece_reason(piece_type: int | None, square: str, board: chess.Board) -> str:
    if piece_type is None:
        return f"no pawn can go to {say_square(square)}"
    name = chess.piece_name(piece_type)
    return f"no {name} can go to {say_square(square)}"


# -- explaining an illegal move ---------------------------------------------


def explain_illegal(parsed: Parsed, board: chess.Board) -> str:
    """A kind, specific reason a move cannot be played.

    "That's not legal" teaches nothing. The reason is the teaching, so this
    works down from the most useful explanation to the least.
    """
    if parsed.reason:
        return parsed.reason

    move = parsed.move
    if move is None:
        return "I couldn't find a piece that can make that move"

    origin, target = move.from_square, move.to_square
    piece = board.piece_at(origin)

    if piece is None:
        return f"there isn't a piece on {say_square(chess.square_name(origin))}"

    if piece.color != board.turn:
        return f"the piece on {say_square(chess.square_name(origin))} isn't yours"

    occupant = board.piece_at(target)
    if occupant is not None and occupant.color == piece.color:
        return (
            f"your own {chess.piece_name(occupant.piece_type)} is already "
            f"on {say_square(chess.square_name(target))}"
        )

    # Would it be legal if the king weren't a problem? If so, that's the reason.
    pseudo = move in board.pseudo_legal_moves
    if pseudo:
        if board.is_check():
            return "your king is in check, so you have to deal with that first"
        return "that would leave your king in check"

    name = chess.piece_name(piece.piece_type)
    if piece.piece_type == chess.PAWN:
        if chess.square_file(origin) != chess.square_file(target) and occupant is None:
            return "a pawn can only move diagonally when it is capturing something"
        if chess.square_file(origin) == chess.square_file(target) and occupant is not None:
            return "a pawn can't capture straight forwards"
        return "a pawn can't reach that square from there"

    if _path_blocked(board, origin, target):
        return f"there's a piece in the way, so the {name} can't get through"

    return f"a {name} can't move like that"


def _path_blocked(board: chess.Board, origin: int, target: int) -> bool:
    between = chess.SquareSet(chess.between(origin, target))
    return any(board.piece_at(sq) is not None for sq in between)


# -- speaking ---------------------------------------------------------------

_PIECE_SPOKEN = {
    "K": "king",
    "Q": "queen",
    "R": "rook",
    "B": "bishop",
    "N": "knight",
}


def say_square(square: str) -> str:
    """'e4' -> 'e four'.

    Spelling the file out stops TTS reading "e4" as a word, and spelling the
    rank out as a word rather than a digit removes any dependence on how a
    given engine happens to verbalise numerals.
    """
    if len(square) != 2:
        return square
    return f"{square[0]} {_rank_word(square[1])}"


def narrate(move: chess.Move, board: chess.Board) -> str:
    """Describe a move so it can be carried out on a physical board.

    `board` is the position BEFORE the move.

    WHY THIS NAMES THE ORIGIN SQUARE, ALWAYS

    SAN only disambiguates when the notation demands it, and speaking SAN
    inherits that. "knight to f three" is unambiguous in the position this code
    thinks it is in -- which is exactly the wrong test, because the position
    that matters is the one on the table. If the two have already drifted by
    one piece, an announcement that is unambiguous here can be ambiguous there,
    the wrong knight gets moved, and the boards are now out by two.

    Naming both squares costs about a second per move and makes every
    announcement self-verifying: if nothing is on g1, you know immediately
    rather than five moves later.

    It also names the things that are NOT one piece moving to one square --
    the castling rook, the pawn en passant removes, the promotion swap --
    because those are where a person moving pieces for a robot goes wrong.
    """
    if board.is_kingside_castling(move) or board.is_queenside_castling(move):
        return _narrate_castling(move, board)

    piece = board.piece_at(move.from_square)
    origin = say_square(chess.square_name(move.from_square))
    target = say_square(chess.square_name(move.to_square))
    name = chess.piece_name(piece.piece_type) if piece else "piece"

    parts = []
    if board.is_en_passant(move):
        # The captured pawn is NOT on the destination square. Saying "takes the
        # pawn on f six" sends a person to an empty square looking for
        # something to remove, which is worse than saying nothing.
        taken = chess.square_name(
            chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        )
        parts.append(f"{name} on {origin} to {target}, capturing en passant")
        parts.append(f"the pawn on {say_square(taken)} comes off the board")
    elif board.is_capture(move):
        captured = _captured_name(move, board)
        parts.append(f"{name} on {origin} takes {captured} on {target}")
    else:
        parts.append(f"{name} on {origin} to {target}")

    if move.promotion:
        promoted = chess.piece_name(move.promotion)
        parts.append(f"then swap that pawn for a {promoted}")

    return ", ".join(parts) + _outcome(move, board)


def _narrate_castling(move: chess.Move, board: chess.Board) -> str:
    """Castling is TWO pieces, and saying 'castles kingside' hides one of them."""
    kingside = board.is_kingside_castling(move)
    rank = "1" if board.turn == chess.WHITE else "8"
    rook_from = ("h" if kingside else "a") + rank
    rook_to = ("f" if kingside else "d") + rank
    king_from = "e" + rank
    king_to = ("g" if kingside else "c") + rank
    side = "kingside" if kingside else "queenside"

    return (
        f"castling {side}: king on {say_square(king_from)} to {say_square(king_to)}, "
        f"and the rook on {say_square(rook_from)} to {say_square(rook_to)}" + _outcome(move, board)
    )


def _captured_name(move: chess.Move, board: chess.Board) -> str:
    if board.is_en_passant(move):
        return "the pawn"
    victim = board.piece_at(move.to_square)
    return f"the {chess.piece_name(victim.piece_type)}" if victim else "the piece"


def _outcome(move: chess.Move, board: chess.Board) -> str:
    """Check or checkmate, tested rather than read off a SAN suffix."""
    board.push(move)
    try:
        if board.is_checkmate():
            return ", checkmate"
        if board.is_check():
            return ", check"
    finally:
        board.pop()
    return ""


def say_move(san: str, board: chess.Board | None = None) -> str:
    """Turn SAN into something worth hearing aloud.

    'Nxf3+' becomes 'knight takes f three, check'. Read literally by a TTS
    engine, SAN is a stream of letters and punctuation.
    """
    text = san.strip()
    if text.startswith("O-O-O") or text.startswith("0-0-0"):
        return "castles queenside" + _suffix(text)
    if text.startswith("O-O") or text.startswith("0-0"):
        return "castles kingside" + _suffix(text)

    body = text.rstrip("+#!?")
    promotion = ""
    if "=" in body:
        body, promoted = body.split("=", 1)
        promotion = f", promoting to a {_PIECE_SPOKEN.get(promoted[:1], 'queen')}"

    piece = ""
    if body and body[0] in _PIECE_SPOKEN:
        piece = _PIECE_SPOKEN[body[0]] + " "
        body = body[1:]

    captures = "takes " if "x" in body else "to "
    body = body.replace("x", "")

    # Any leading disambiguator ("bd" in "Nbd7") is spoken as a source hint.
    target = body[-2:]
    hint = body[:-2]
    origin = ""
    if hint:
        # "Nbd7" -- the hint is which of two identical pieces moved. "knight
        # from b" is not something anyone says; name the file or the rank.
        if hint[0] in FILES:
            origin = f"from the {hint[0]} file "
        else:
            origin = f"from rank {_rank_word(hint[0])} "

    if not piece:
        # A pawn move: "e four" reads better than "pawn to e four".
        spoken = (
            f"{hint} takes {say_square(target)}"
            if captures == "takes " and hint
            else say_square(target)
        )
        return spoken + promotion + _suffix(text)

    return f"{piece}{origin}{captures}{say_square(target)}{promotion}{_suffix(text)}"


def _suffix(san: str) -> str:
    if san.endswith("#"):
        return ", checkmate"
    if san.endswith("+"):
        return ", check"
    return ""


def spoken_forms(move: chess.Move, board: chess.Board) -> list[str]:
    """Every way a person might SAY this move.

    Used to build the per-turn Vosk grammar. Being generous here costs nothing
    -- the grammar is still closed, so an extra phrasing widens what the child
    can say without widening what the recogniser can return.
    """
    san = board.san(move)
    forms = set()

    if san.startswith("O-O-O"):
        return ["castle queenside", "long castle", "castles queenside"]
    if san.startswith("O-O"):
        return ["castle kingside", "short castle", "castles kingside"]

    target = chess.square_name(move.to_square)
    origin = chess.square_name(move.from_square)
    piece = board.piece_at(move.from_square)
    captures = board.is_capture(move)

    target_spoken = f"{target[0]} {_rank_word(target[1])}"
    origin_spoken = f"{origin[0]} {_rank_word(origin[1])}"

    if piece is not None and piece.piece_type != chess.PAWN:
        name = chess.piece_name(piece.piece_type)
        forms.add(f"{name} {target_spoken}")
        forms.add(f"{name} to {target_spoken}")
        forms.add(f"{name} {origin_spoken} {target_spoken}")
        if captures:
            forms.add(f"{name} takes {target_spoken}")
            forms.add(f"{name} captures {target_spoken}")
    else:
        forms.add(target_spoken)
        forms.add(f"{origin_spoken} {target_spoken}")
        if captures:
            forms.add(f"{origin[0]} takes {target_spoken}")
            forms.add(f"pawn takes {target_spoken}")

    if move.promotion:
        promoted = chess.piece_name(move.promotion)
        for form in list(forms):
            forms.add(f"{form} {promoted}")

    return sorted(forms)


def _rank_word(digit: str) -> str:
    """Ranks are spoken as words in the grammar so Vosk has a word to match."""
    words = {
        "1": "one",
        "2": "two",
        "3": "three",
        "4": "four",
        "5": "five",
        "6": "six",
        "7": "seven",
        "8": "eight",
    }
    return words.get(digit, digit)
