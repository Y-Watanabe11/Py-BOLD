"""COBOL tokenizer.

Supports standard fixed-format COBOL (72-char code area, col-7 indicator).
Column layout (1-indexed):
  1–6   : sequence numbers (ignored)
  7     : indicator (* or / = comment, space = normal)
  8–72  : code (Area A cols 8-11 + Area B cols 12-72)
  73+   : identification (ignored)
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import List


class TT(Enum):
    # ── Structure keywords ───────────────────────────────────────────────────
    IDENTIFICATION = auto(); DATA = auto(); PROCEDURE = auto()
    DIVISION = auto(); SECTION = auto()
    PROGRAM_ID = auto(); WORKING_STORAGE = auto()
    # ── Statement keywords ───────────────────────────────────────────────────
    MOVE = auto(); TO = auto()
    COMPUTE = auto()
    ADD = auto(); SUBTRACT = auto(); MULTIPLY = auto(); DIVIDE = auto()
    BY = auto(); FROM = auto(); INTO = auto(); GIVING = auto()
    IF = auto(); THEN = auto(); ELSE = auto(); END_IF = auto()
    PERFORM = auto()
    DISPLAY = auto()
    STOP = auto(); RUN = auto()
    # ── Data-definition keywords ─────────────────────────────────────────────
    PIC = auto(); PICTURE = auto(); VALUE = auto(); IS = auto()
    # ── Condition keywords ───────────────────────────────────────────────────
    NOT = auto(); AND = auto(); OR = auto()
    GREATER = auto(); LESS = auto(); EQUAL = auto(); THAN = auto()
    # ── Terminals ────────────────────────────────────────────────────────────
    LEVEL = auto()   # level numbers 01-49, 66, 77, 88
    IDENT = auto()
    NUMBER = auto()
    STRING = auto()
    # ── Operators ────────────────────────────────────────────────────────────
    EQ = auto(); PLUS = auto(); MINUS = auto(); STAR = auto(); SLASH = auto()
    LPAREN = auto(); RPAREN = auto()
    GT = auto(); LT = auto(); GTE = auto(); LTE = auto()
    DOT = auto()
    # ── Sentinel ─────────────────────────────────────────────────────────────
    EOF = auto()


_KEYWORDS: dict[str, TT] = {
    "IDENTIFICATION": TT.IDENTIFICATION, "DATA": TT.DATA,
    "PROCEDURE": TT.PROCEDURE, "DIVISION": TT.DIVISION,
    "SECTION": TT.SECTION, "PROGRAM-ID": TT.PROGRAM_ID,
    "WORKING-STORAGE": TT.WORKING_STORAGE,
    "MOVE": TT.MOVE, "TO": TT.TO,
    "COMPUTE": TT.COMPUTE,
    "ADD": TT.ADD, "SUBTRACT": TT.SUBTRACT,
    "MULTIPLY": TT.MULTIPLY, "DIVIDE": TT.DIVIDE,
    "BY": TT.BY, "FROM": TT.FROM, "INTO": TT.INTO, "GIVING": TT.GIVING,
    "IF": TT.IF, "THEN": TT.THEN, "ELSE": TT.ELSE, "END-IF": TT.END_IF,
    "PERFORM": TT.PERFORM,
    "DISPLAY": TT.DISPLAY,
    "STOP": TT.STOP, "RUN": TT.RUN,
    "PIC": TT.PIC, "PICTURE": TT.PICTURE,
    "VALUE": TT.VALUE, "IS": TT.IS,
    "NOT": TT.NOT, "AND": TT.AND, "OR": TT.OR,
    "GREATER": TT.GREATER, "LESS": TT.LESS, "EQUAL": TT.EQUAL, "THAN": TT.THAN,
}

# Level numbers that introduce data items
_VALID_LEVELS = frozenset(range(1, 50)) | {66, 77, 88}


@dataclass
class Token:
    type: TT
    value: str
    line: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, L{self.line})"


def tokenize(source: str) -> List[Token]:
    """Return a flat list of tokens, terminated by a single EOF token."""
    tokens: List[Token] = []

    for line_num, raw in enumerate(source.splitlines(), 1):
        # ── Fixed-format column handling ──────────────────────────────────
        if len(raw) > 6 and raw[6] in ("*", "/"):
            continue  # comment or debug line
        # Extract code area: columns 7–72 (0-indexed: 6–71)
        code = (raw[6:72] if len(raw) > 6 else raw).rstrip()
        if not code.strip():
            continue

        i = 0
        n = len(code)

        while i < n:
            ch = code[i]

            # ── Whitespace ────────────────────────────────────────────────
            if ch.isspace():
                i += 1
                continue

            # ── String literals ───────────────────────────────────────────
            if ch in ('"', "'"):
                q = ch
                j = i + 1
                while j < n and code[j] != q:
                    j += 1
                tokens.append(Token(TT.STRING, code[i : j + 1], line_num))
                i = j + 1
                continue

            # ── Two-character operators ───────────────────────────────────
            two = code[i : i + 2]
            if two == ">=":
                tokens.append(Token(TT.GTE, two, line_num)); i += 2; continue
            if two == "<=":
                tokens.append(Token(TT.LTE, two, line_num)); i += 2; continue

            # ── Single-character operators ────────────────────────────────
            _single: dict[str, TT] = {
                "=": TT.EQ, "+": TT.PLUS, "-": TT.MINUS,
                "*": TT.STAR, "/": TT.SLASH,
                "(": TT.LPAREN, ")": TT.RPAREN,
                ">": TT.GT, "<": TT.LT,
                ".": TT.DOT,
            }
            if ch in _single:
                tokens.append(Token(_single[ch], ch, line_num)); i += 1; continue

            # ── Numeric literals ──────────────────────────────────────────
            if ch.isdigit():
                j = i + 1
                while j < n and code[j].isdigit():
                    j += 1
                # Decimal point: only consume '.' if immediately followed by a digit
                if j < n and code[j] == "." and j + 1 < n and code[j + 1].isdigit():
                    j += 1  # consume '.'
                    while j < n and code[j].isdigit():
                        j += 1
                num = code[i:j]
                # Decide: data-item level number or plain numeric literal?
                if num.isdigit() and int(num) in _VALID_LEVELS:
                    tokens.append(Token(TT.LEVEL, num.zfill(2), line_num))
                else:
                    tokens.append(Token(TT.NUMBER, num, line_num))
                i = j
                continue

            # ── Identifiers and keywords ──────────────────────────────────
            if ch.isalpha() or ch == "_":
                j = i + 1
                while j < n and (code[j].isalnum() or code[j] in "-_"):
                    j += 1
                # Trim trailing hyphens (can appear at line-continuation boundaries)
                while j > i + 1 and code[j - 1] == "-":
                    j -= 1
                word = code[i:j].upper()
                tt = _KEYWORDS.get(word, TT.IDENT)
                tokens.append(Token(tt, word, line_num))
                i = j
                continue

            # ── Skip unrecognised characters ──────────────────────────────
            i += 1

    tokens.append(Token(TT.EOF, "", 0))
    return tokens
