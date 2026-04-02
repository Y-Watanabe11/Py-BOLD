"""AST Printer — LLM-ready serializer for CobolProgram nodes.

Converts the typed AST produced by CobolParser into a structured,
human-readable text block suitable for injection into an LLM prompt.

Design rationale
----------------
An LLM needs *semantic density*, not raw syntax.  The output format:
  1. Names every node type explicitly ("MOVE", "COMPUTE", "IF-BRANCH")
     so the LLM understands the structural role without re-parsing.
  2. Inlines PIC metadata with each variable so the LLM can infer
     Python types (9(6) → int, 9(7)V99 → Decimal, X → str).
  3. Renders expression trees as infix strings — compact and unambiguous.
  4. Uses indentation + box-drawing chars to mirror AST depth, which
     helps the LLM reason about scope without extra prompting.
"""
from __future__ import annotations
from typing import List

from .ast_nodes import (
    CobolProgram, DataItem, Paragraph, Statement,
    Expr, Condition,
    Literal, VarRef, BinOp, UnaryMinus,
    Comparison, BoolOp,
    MoveStmt, ComputeStmt, AddStmt, SubtractStmt,
    MultiplyStmt, DivideStmt, IfStmt,
    PerformStmt, DisplayStmt, StopRunStmt,
)


# ── Public entry point ────────────────────────────────────────────────────────

def program_to_prompt_block(program: CobolProgram) -> str:
    """Return a single string containing the full LLM-ready AST dump."""
    lines: List[str] = []
    _render_program(program, lines)
    return "\n".join(lines)


# ── Program ───────────────────────────────────────────────────────────────────

def _render_program(program: CobolProgram, out: List[str]) -> None:
    width = 60
    out.append("╔" + "═" * width + "╗")
    out.append(f"║  COBOL PROGRAM AST  —  {program.program_id:<{width - 23}}║")
    out.append("╚" + "═" * width + "╝")

    # ── DATA DIVISION ─────────────────────────────────────────────
    out.append("")
    out.append("── DATA DIVISION ── Working-Storage Variables ──────────────")
    out.append(
        f"   {'LEVEL':<6} {'NAME':<26} {'PIC':<16} {'INIT VALUE'}"
    )
    out.append("   " + "-" * 57)
    for item in program.data_items:
        _render_data_item(item, out, indent=0)

    # ── PROCEDURE DIVISION ────────────────────────────────────────
    out.append("")
    out.append(
        f"── PROCEDURE DIVISION ── {len(program.paragraphs)} paragraph(s) ─────────────"
    )
    for para in program.paragraphs:
        out.append("")
        _render_paragraph(para, out)


# ── Data items ────────────────────────────────────────────────────────────────

def _render_data_item(item: DataItem, out: List[str], indent: int) -> None:
    pad = "   " + "  " * indent
    pic_str = item.pic or "(group)"
    val_str = item.initial_value or ""

    # Compiler annotation: infer the Python type from the PIC clause
    py_type = _infer_python_type(item.pic)

    out.append(
        f"{pad}[L{item.level:02d}] {item.name:<26} PIC {pic_str:<16}"
        f" init={val_str!r:<10}  # → Python {py_type}"
    )
    for child in item.children:
        _render_data_item(child, out, indent + 1)


def _infer_python_type(pic: str | None) -> str:
    """Heuristic: map a PIC clause to the most natural Python type.

    Compiler theory note: a PIC clause is itself a mini-language.
    '9' means numeric digit, 'X' alphanumeric, 'V' an implied decimal
    point (no physical character stored).  We parse just enough to
    suggest the right Python primitive.
    """
    if pic is None:
        return "dict  # group item → dataclass"
    p = pic.upper()
    if "V" in p or "." in p:
        return "Decimal"   # implied decimal point → fixed-precision
    if p.startswith("9"):
        return "int"
    if "X" in p or "A" in p:
        return "str"
    return "Any"


# ── Paragraphs ────────────────────────────────────────────────────────────────

def _render_paragraph(para: Paragraph, out: List[str]) -> None:
    out.append(f"  ┌─ PARAGRAPH: {para.name}  (L{para.line})")
    for i, stmt in enumerate(para.statements, 1):
        prefix = f"  │  [{i:02d}] "
        _render_stmt(stmt, out, prefix=prefix, continuation="  │       ")
    out.append("  └─ END PARAGRAPH")


# ── Statements ────────────────────────────────────────────────────────────────

def _render_stmt(
    stmt: Statement,
    out: List[str],
    prefix: str,
    continuation: str,
) -> None:
    """Dispatch to the per-statement renderer.

    Compiler theory note: each statement class corresponds to a distinct
    node in our AST.  By printing the node *type* explicitly, the LLM
    sees the intent (MOVE = assignment, COMPUTE = expression eval) rather
    than inferring it from keyword tokens.
    """
    if isinstance(stmt, MoveStmt):
        _render_move(stmt, out, prefix)
    elif isinstance(stmt, ComputeStmt):
        _render_compute(stmt, out, prefix)
    elif isinstance(stmt, AddStmt):
        _render_add(stmt, out, prefix)
    elif isinstance(stmt, SubtractStmt):
        _render_subtract(stmt, out, prefix)
    elif isinstance(stmt, MultiplyStmt):
        _render_multiply(stmt, out, prefix)
    elif isinstance(stmt, DivideStmt):
        _render_divide(stmt, out, prefix)
    elif isinstance(stmt, IfStmt):
        _render_if(stmt, out, prefix, continuation)
    elif isinstance(stmt, PerformStmt):
        out.append(f"{prefix}PERFORM  → paragraph={stmt.paragraph!r}")
    elif isinstance(stmt, DisplayStmt):
        items_str = ", ".join(_expr_str(e) for e in stmt.items)
        out.append(f"{prefix}DISPLAY  [{items_str}]")
    elif isinstance(stmt, StopRunStmt):
        out.append(f"{prefix}STOP RUN")


def _render_move(stmt: MoveStmt, out: List[str], prefix: str) -> None:
    targets = ", ".join(stmt.targets)
    out.append(
        f"{prefix}MOVE     source={_expr_str(stmt.source)}  →  target=[{targets}]"
        f"  (L{stmt.line})"
    )


def _render_compute(stmt: ComputeStmt, out: List[str], prefix: str) -> None:
    out.append(
        f"{prefix}COMPUTE  {stmt.target} = {_expr_str(stmt.expression)}"
        f"  (L{stmt.line})"
    )


def _render_add(stmt: AddStmt, out: List[str], prefix: str) -> None:
    ops = " + ".join(_expr_str(e) for e in stmt.operands)
    targets = ", ".join(stmt.targets)
    out.append(
        f"{prefix}ADD      ({ops})  →  target=[{targets}]  (L{stmt.line})"
    )


def _render_subtract(stmt: SubtractStmt, out: List[str], prefix: str) -> None:
    subs = " - ".join(_expr_str(e) for e in stmt.subtrahends)
    targets = ", ".join(stmt.targets)
    out.append(
        f"{prefix}SUBTRACT ({subs})  FROM  [{targets}]  (L{stmt.line})"
    )


def _render_multiply(stmt: MultiplyStmt, out: List[str], prefix: str) -> None:
    targets = ", ".join(stmt.targets)
    out.append(
        f"{prefix}MULTIPLY {_expr_str(stmt.operand)}  BY  [{targets}]  (L{stmt.line})"
    )


def _render_divide(stmt: DivideStmt, out: List[str], prefix: str) -> None:
    targets = ", ".join(stmt.targets)
    out.append(
        f"{prefix}DIVIDE   {_expr_str(stmt.divisor)}  INTO  [{targets}]  (L{stmt.line})"
    )


def _render_if(
    stmt: IfStmt,
    out: List[str],
    prefix: str,
    continuation: str,
) -> None:
    out.append(
        f"{prefix}IF       condition=[ {_cond_str(stmt.condition)} ]  (L{stmt.line})"
    )
    # THEN branch
    then_pfx = continuation + "  THEN  │  "
    then_cont = continuation + "        │  "
    for s in stmt.then_stmts:
        _render_stmt(s, out, prefix=then_pfx, continuation=then_cont)
    # ELSE branch (only if non-empty)
    if stmt.else_stmts:
        else_pfx = continuation + "  ELSE  │  "
        else_cont = continuation + "        │  "
        for s in stmt.else_stmts:
            _render_stmt(s, out, prefix=else_pfx, continuation=else_cont)


# ── Expression → infix string ─────────────────────────────────────────────────

def _expr_str(expr: Expr) -> str:
    """Render an expression node as a compact infix string.

    Compiler theory note: this is essentially a pretty-printer pass over
    the expression sub-tree.  BinOp nodes carry an explicit operator and
    two child Expr nodes — the classic recursive structure of an
    expression grammar (additive over multiplicative over unary over primary).
    """
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, VarRef):
        return expr.name
    if isinstance(expr, BinOp):
        # Parenthesise lower-precedence sub-expressions for readability
        return f"({_expr_str(expr.left)} {expr.op} {_expr_str(expr.right)})"
    if isinstance(expr, UnaryMinus):
        return f"-{_expr_str(expr.operand)}"
    return "?"


# ── Condition → string ────────────────────────────────────────────────────────

def _cond_str(cond: Condition) -> str:
    if isinstance(cond, Comparison):
        return (
            f"{_expr_str(cond.left)} {cond.op} {_expr_str(cond.right)}"
        )
    if isinstance(cond, BoolOp):
        return (
            f"({_cond_str(cond.left)} {cond.op} {_cond_str(cond.right)})"
        )
    return "?"
