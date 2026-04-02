"""Lexer unit tests.

Tests are written at the Token level — they verify that the lexer
emits the correct (type, value) pairs for inputs that are historically
ambiguous in COBOL's fixed-format, context-free tokenisation.

Key hazard: the lexer has no context, so it applies the *same* rule to
every integer it sees.  Integers in range 1–49 plus 66, 77, 88 are
valid COBOL level numbers AND valid numeric constants.  The lexer
always emits TT.LEVEL for these; the parser is responsible for
recovering correct semantics in each context (e.g. PIC strings,
COMPUTE expressions).  Tests here pin *lexer* behaviour; the recovery
is tested in test_ast_generation.py.
"""
import pytest
from tests.helpers import tokenize, TT, Token


def tok_types(source: str) -> list[TT]:
    return [t.type for t in tokenize(source) if t.type != TT.EOF]


def tok_pairs(source: str) -> list[tuple[TT, str]]:
    return [(t.type, t.value) for t in tokenize(source) if t.type != TT.EOF]


# ── Comment / layout handling ─────────────────────────────────────────────────

class TestFixedFormatLayout:
    def test_comment_lines_are_skipped(self):
        """Col-7 indicator '*' marks a comment; the line must produce no tokens."""
        source = "      * This entire line is a COBOL comment\n"
        assert tok_types(source) == []

    def test_debug_slash_lines_are_skipped(self):
        """Col-7 indicator '/' is a debug/listing line; also skipped."""
        source = "      / EJECT\n"
        assert tok_types(source) == []

    def test_blank_lines_are_skipped(self):
        source = "\n   \n\n"
        assert tok_types(source) == []

    def test_sequence_area_does_not_produce_tokens(self):
        """Cols 1–6 are the sequence area and must never appear in the token stream."""
        # '000010' in cols 1-6, then space in col 7, then 'MOVE' in code area
        source = "000010 MOVE"
        tokens = tokenize(source)
        types = [t.type for t in tokens if t.type != TT.EOF]
        assert TT.MOVE in types
        # The number '000010' must NOT appear as a token
        assert TT.NUMBER not in types
        assert TT.LEVEL not in types

    def test_identification_area_beyond_col_72_ignored(self):
        """Content beyond col 72 is the identification area; must be stripped.

        Col layout (1-indexed): cols 1-6 = sequence, col 7 = indicator,
        cols 8-72 = code area, cols 73+ = identification area (ignored).
        We pad the line to exactly 73+ chars so the trailing noise
        sits in the identification area, not the code area.
        """
        # 7 spaces (cols 1-7) + 'STOP RUN.' (9 chars, cols 8-16)
        # + spaces to fill cols 17-72 (56 spaces) + 'NOISEXYZ' (cols 73+)
        code_line = "       STOP RUN." + " " * 56 + "NOISEXYZ"
        assert len(code_line) > 72   # confirm noise is beyond col 72
        types = tok_types(code_line)
        assert TT.STOP in types
        assert TT.RUN in types
        # 'NOISEXYZ' is beyond col 72 and must NOT appear as an IDENT token
        assert TT.IDENT not in types


# ── Keyword tokenisation ──────────────────────────────────────────────────────

class TestKeywords:
    def test_basic_division_keywords(self):
        source = "       IDENTIFICATION DIVISION."
        types = tok_types(source)
        assert types == [TT.IDENTIFICATION, TT.DIVISION, TT.DOT]

    def test_hyphenated_keyword_program_id(self):
        source = "       PROGRAM-ID."
        assert TT.PROGRAM_ID in tok_types(source)

    def test_hyphenated_keyword_working_storage(self):
        source = "       WORKING-STORAGE SECTION."
        types = tok_types(source)
        assert TT.WORKING_STORAGE in types

    def test_hyphenated_keyword_end_if(self):
        source = "       END-IF."
        assert TT.END_IF in tok_types(source)

    def test_keywords_are_case_insensitive(self):
        """The lexer uppercases all tokens before lookup."""
        lower = tok_types("       move")
        upper = tok_types("       MOVE")
        assert lower == upper == [TT.MOVE]

    def test_hyphenated_ident_is_not_a_keyword(self):
        """WS-CUST-ID is a user-defined name, not a reserved word."""
        source = "       WS-CUST-ID"
        assert tok_types(source) == [TT.IDENT]


# ── Level numbers vs numeric literals ────────────────────────────────────────

class TestLevelVsNumber:
    def test_level_01_produces_level_token(self):
        source = "       01"
        pairs = tok_pairs(source)
        assert pairs == [(TT.LEVEL, "01")]

    def test_level_77_produces_level_token(self):
        source = "       77"
        pairs = tok_pairs(source)
        assert pairs == [(TT.LEVEL, "77")]

    def test_level_88_produces_level_token(self):
        source = "       88"
        pairs = tok_pairs(source)
        assert pairs == [(TT.LEVEL, "88")]

    def test_small_integer_in_valid_level_range_produces_level_token(self):
        """
        The lexer is context-free: '15' in COMPUTE X = 15 is STILL a LEVEL
        token at lex time.  This is the 'maximal munch' ambiguity.
        The parser recovers it in _parse_primary — see test_ast_generation.py.
        """
        source = "       15"
        pairs = tok_pairs(source)
        assert pairs == [(TT.LEVEL, "15")]

    def test_integer_outside_level_range_produces_number_token(self):
        """99 and above are not valid COBOL level numbers → plain NUMBER."""
        source = "       99"
        pairs = tok_pairs(source)
        assert pairs == [(TT.NUMBER, "99")]

    def test_large_integer_is_number(self):
        source = "       1000"
        pairs = tok_pairs(source)
        assert pairs == [(TT.NUMBER, "1000")]

    def test_decimal_literal_is_number(self):
        source = "       1500.00"
        pairs = tok_pairs(source)
        assert pairs == [(TT.NUMBER, "1500.00")]


# ── String literals ───────────────────────────────────────────────────────────

class TestStringLiterals:
    def test_single_quoted_string(self):
        source = "       'HELLO'"
        pairs = tok_pairs(source)
        assert pairs == [(TT.STRING, "'HELLO'")]

    def test_double_quoted_string(self):
        source = '       "WORLD"'
        pairs = tok_pairs(source)
        assert pairs == [(TT.STRING, '"WORLD"')]

    def test_string_with_spaces(self):
        source = "       'FINAL AMOUNT: '"
        pairs = tok_pairs(source)
        assert pairs == [(TT.STRING, "'FINAL AMOUNT: '")]

    def test_single_char_string(self):
        source = "       'Y'"
        pairs = tok_pairs(source)
        assert pairs == [(TT.STRING, "'Y'")]


# ── Operators ─────────────────────────────────────────────────────────────────

class TestOperators:
    def test_gte_operator(self):
        source = "       >="
        assert tok_types(source) == [TT.GTE]

    def test_lte_operator(self):
        source = "       <="
        assert tok_types(source) == [TT.LTE]

    def test_gt_operator(self):
        source = "       >"
        assert tok_types(source) == [TT.GT]

    def test_lt_operator(self):
        source = "       <"
        assert tok_types(source) == [TT.LT]

    def test_eq_operator(self):
        source = "       ="
        assert tok_types(source) == [TT.EQ]

    def test_arithmetic_operators(self):
        source = "       + - * /"
        assert tok_types(source) == [TT.PLUS, TT.MINUS, TT.STAR, TT.SLASH]

    def test_dot_terminator(self):
        source = "       ."
        assert tok_types(source) == [TT.DOT]
