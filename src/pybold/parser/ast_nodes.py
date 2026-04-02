"""AST node definitions for the COBOL parser.

Covers the subset needed by the Py-BOLD pipeline:
  DATA DIVISION / WORKING-STORAGE
  PROCEDURE DIVISION statements (MOVE, COMPUTE, ADD, SUBTRACT,
                                  MULTIPLY, DIVIDE, IF, PERFORM,
                                  DISPLAY, STOP RUN)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Union


# ── Data Items ────────────────────────────────────────────────────────────────

@dataclass
class DataItem:
    """One entry from WORKING-STORAGE SECTION."""
    level: int
    name: str
    pic: Optional[str]            # e.g. "9(6)V9(2)"  – None for group items
    initial_value: Optional[str]  # VALUE clause literal
    line: int
    children: List[DataItem] = field(default_factory=list)

    def is_elementary(self) -> bool:
        return self.pic is not None


# ── Expressions ───────────────────────────────────────────────────────────────

@dataclass
class Literal:
    value: str
    line: int

@dataclass
class VarRef:
    name: str
    line: int

@dataclass
class BinOp:
    op: str       # "+", "-", "*", "/"
    left: "Expr"
    right: "Expr"
    line: int

@dataclass
class UnaryMinus:
    operand: "Expr"
    line: int

Expr = Union[Literal, VarRef, BinOp, UnaryMinus]


# ── Conditions ────────────────────────────────────────────────────────────────

@dataclass
class Comparison:
    op: str       # ">", "<", ">=", "<=", "=", "NOT >"…
    left: Expr
    right: Expr
    line: int

@dataclass
class BoolOp:
    op: str       # "AND", "OR"
    left: "Condition"
    right: "Condition"
    line: int

Condition = Union[Comparison, BoolOp]


# ── Statements ────────────────────────────────────────────────────────────────

@dataclass
class MoveStmt:
    source: Expr
    targets: List[str]    # MOVE x TO a b c
    line: int

@dataclass
class ComputeStmt:
    target: str
    expression: Expr
    line: int

@dataclass
class AddStmt:
    operands: List[Expr]
    targets: List[str]    # ADD a b TO x  or  ADD a GIVING x
    line: int

@dataclass
class SubtractStmt:
    subtrahends: List[Expr]
    targets: List[str]    # SUBTRACT a FROM x  or  … GIVING z
    line: int

@dataclass
class MultiplyStmt:
    operand: Expr
    targets: List[str]    # MULTIPLY x BY y  →  y = y * x
    line: int

@dataclass
class DivideStmt:
    divisor: Expr
    targets: List[str]    # DIVIDE x INTO y  →  y = y / x
    line: int

@dataclass
class IfStmt:
    condition: Condition
    then_stmts: List["Statement"]
    else_stmts: List["Statement"]
    line: int

@dataclass
class PerformStmt:
    paragraph: str
    line: int

@dataclass
class DisplayStmt:
    items: List[Expr]
    line: int

@dataclass
class StopRunStmt:
    line: int

Statement = Union[
    MoveStmt, ComputeStmt, AddStmt, SubtractStmt, MultiplyStmt, DivideStmt,
    IfStmt, PerformStmt, DisplayStmt, StopRunStmt,
]


# ── Program ───────────────────────────────────────────────────────────────────

@dataclass
class Paragraph:
    name: str
    statements: List[Statement]
    line: int

@dataclass
class CobolProgram:
    program_id: str
    data_items: List[DataItem]   # flat — nested group items carry their own level
    paragraphs: List[Paragraph]
