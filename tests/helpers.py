"""Shared test helpers for the Py-BOLD parser test suite.

Design note
-----------
The COBOL parser requires a complete program skeleton (IDENTIFICATION →
DATA → PROCEDURE DIVISION) for every parse call.  These helpers wrap a
minimal snippet in that skeleton so each test exercises exactly one
concept without boilerplate.

Fixed-format column reminder (1-indexed):
  cols  1–6 : sequence area (ignored)
  col   7   : indicator  (* or / = comment)
  cols  8–72: code area (Area A: 8-11, Area B: 12-72)

A 7-space leading indent puts the first code character at col 8 — the
minimum required for the lexer to treat the line as non-comment code.
"""
import sys
from pathlib import Path

# Allow imports without `pip install -e .`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from typing import List
from pybold.parser.lexer import tokenize, Token, TT
from pybold.parser.cobol_parser import CobolParser
from pybold.parser.ast_nodes import (
    CobolProgram, DataItem, Paragraph, Statement,
    Literal, VarRef, BinOp, UnaryMinus,
    Comparison, BoolOp,
    MoveStmt, ComputeStmt, AddStmt, SubtractStmt,
    MultiplyStmt, DivideStmt, IfStmt,
    PerformStmt, DisplayStmt, StopRunStmt,
)


# ── Skeleton wrappers ─────────────────────────────────────────────────────────

_IDENT = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. TEST-PROG.\n"
)
_DATA_HEADER = (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
)
_PROC_HEADER = (
    "       PROCEDURE DIVISION.\n"
    "       TEST-PARA.\n"
)
_STOP = "           STOP RUN.\n"


def make_full_program(ws_lines: str = "", proc_lines: str = "") -> str:
    """Build a syntactically valid COBOL program from snippet strings."""
    return (
        _IDENT
        + _DATA_HEADER
        + (ws_lines + "\n" if ws_lines else "")
        + _PROC_HEADER
        + (proc_lines + "\n" if proc_lines else "")
        + _STOP
    )


# ── Parse helpers ─────────────────────────────────────────────────────────────

def parse_program(source: str) -> CobolProgram:
    return CobolParser(tokenize(source)).parse()


def parse_data(ws_lines: str) -> List[DataItem]:
    """Parse a WORKING-STORAGE snippet; return the DataItem list."""
    return parse_program(make_full_program(ws_lines=ws_lines)).data_items


def parse_stmts(proc_lines: str) -> List[Statement]:
    """Parse procedure statements; return the statement list of TEST-PARA."""
    return parse_program(
        make_full_program(proc_lines=proc_lines)
    ).paragraphs[0].statements
