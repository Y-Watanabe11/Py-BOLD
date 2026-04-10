"""Data Flow Graph (DFG) builder.

Takes a parsed CobolProgram and produces a NetworkX DiGraph where:
  - Nodes  = variables from WORKING-STORAGE (+ external literal sources)
  - Edges  = data dependencies  (A → B means "A's value flows into B")

Node attributes
  type          : "variable" | "literal"
  pic           : PIC clause string (variables only)
  initial_value : VALUE clause (variables only)
  level         : data-item level number

Edge attributes
  op        : statement type that creates the dependency
              ("MOVE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE")
  paragraph : paragraph in which the statement appears
  line      : source line number
  branch    : "then" | "else" | None  (for edges inside IF branches)
"""
from __future__ import annotations
from typing import List, Optional
import networkx as nx

from ..parser.ast_nodes import (
    CobolProgram, DataItem, Paragraph,
    Statement, Expr, Condition,
    Literal, VarRef, BinOp, UnaryMinus,
    Comparison, BoolOp,
    MoveStmt, ComputeStmt, AddStmt, SubtractStmt,
    MultiplyStmt, DivideStmt, IfStmt,
    PerformStmt, DisplayStmt, StopRunStmt,
)


def build_dfg(program: CobolProgram) -> nx.DiGraph:
    """Return the full Data Flow Graph for *program*."""
    G = nx.DiGraph()
    _add_variable_nodes(G, program.data_items)
    for para in program.paragraphs:
        _process_paragraph(G, para)
    return G


# ── Node population ───────────────────────────────────────────────────────────

def _add_variable_nodes(G: nx.DiGraph, items: List[DataItem]) -> None:
    for item in items:
        G.add_node(
            item.name,
            type="variable",
            pic=item.pic or "",
            initial_value=item.initial_value or "",
            level=item.level,
        )
        if item.children:
            _add_variable_nodes(G, item.children)


def _ensure_node(G: nx.DiGraph, name: str) -> None:
    """Add a node for a name that wasn't declared in WORKING-STORAGE."""
    if name not in G:
        G.add_node(name, type="undeclared", pic="", initial_value="", level=0)


# ── Statement processing ──────────────────────────────────────────────────────

def _process_paragraph(G: nx.DiGraph, para: Paragraph) -> None:
    for stmt in para.statements:
        _process_stmt(G, stmt, para.name, branch=None)


def _process_stmt(
    G: nx.DiGraph,
    stmt: Statement,
    paragraph: str,
    branch: Optional[str],
) -> None:
    meta = dict(paragraph=paragraph, branch=branch)

    if isinstance(stmt, MoveStmt):
        sources = _vars_in_expr(stmt.source)
        for target in stmt.targets:
            _ensure_node(G, target)
            for src in sources:
                _ensure_node(G, src)
                G.add_edge(src, target, op="MOVE", line=stmt.line, **meta)
            if not sources:  # literal source — record as constant flow
                lit_node = f"LITERAL:{_expr_repr(stmt.source)}"
                if lit_node not in G:
                    G.add_node(lit_node, type="literal", pic="", initial_value="", level=0)
                G.add_edge(lit_node, target, op="MOVE", line=stmt.line, **meta)

    elif isinstance(stmt, ComputeStmt):
        target = stmt.target
        _ensure_node(G, target)
        for src in _vars_in_expr(stmt.expression):
            _ensure_node(G, src)
            G.add_edge(src, target, op="COMPUTE", line=stmt.line, **meta)

    elif isinstance(stmt, AddStmt):
        for target in stmt.targets:
            _ensure_node(G, target)
            for op_expr in stmt.operands:
                for src in _vars_in_expr(op_expr):
                    _ensure_node(G, src)
                    G.add_edge(src, target, op="ADD", line=stmt.line, **meta)

    elif isinstance(stmt, SubtractStmt):
        for target in stmt.targets:
            _ensure_node(G, target)
            for sub_expr in stmt.subtrahends:
                for src in _vars_in_expr(sub_expr):
                    _ensure_node(G, src)
                    G.add_edge(src, target, op="SUBTRACT", line=stmt.line, **meta)

    elif isinstance(stmt, MultiplyStmt):
        for target in stmt.targets:
            _ensure_node(G, target)
            for src in _vars_in_expr(stmt.operand):
                _ensure_node(G, src)
                G.add_edge(src, target, op="MULTIPLY", line=stmt.line, **meta)

    elif isinstance(stmt, DivideStmt):
        for target in stmt.targets:
            _ensure_node(G, target)
            for src in _vars_in_expr(stmt.divisor):
                _ensure_node(G, src)
                G.add_edge(src, target, op="DIVIDE", line=stmt.line, **meta)

    elif isinstance(stmt, IfStmt):
        # Condition variables influence ALL variables assigned in either branch
        cond_vars = _vars_in_condition(stmt.condition)
        for sub in stmt.then_stmts:
            _process_stmt(G, sub, paragraph, branch="then")
            # Annotate condition dependency
            for assigned in _assigned_by(sub):
                _ensure_node(G, assigned)
                for cv in cond_vars:
                    _ensure_node(G, cv)
                    if not G.has_edge(cv, assigned):
                        G.add_edge(
                            cv, assigned,
                            op="IF-CONDITION", line=stmt.line, **meta,
                        )
        for sub in stmt.else_stmts:
            _process_stmt(G, sub, paragraph, branch="else")
            for assigned in _assigned_by(sub):
                _ensure_node(G, assigned)
                for cv in cond_vars:
                    _ensure_node(G, cv)
                    if not G.has_edge(cv, assigned):
                        G.add_edge(
                            cv, assigned,
                            op="IF-CONDITION", line=stmt.line, **meta,
                        )

    # PERFORM, DISPLAY, STOP RUN: no data flow edges


# ── Expression helpers ────────────────────────────────────────────────────────

def _vars_in_expr(expr: Expr) -> List[str]:
    """Return all variable names referenced in *expr*."""
    if isinstance(expr, VarRef):
        return [expr.name]
    if isinstance(expr, Literal):
        return []
    if isinstance(expr, BinOp):
        return _vars_in_expr(expr.left) + _vars_in_expr(expr.right)
    if isinstance(expr, UnaryMinus):
        return _vars_in_expr(expr.operand)
    return []


def _vars_in_condition(cond: Condition) -> List[str]:
    if isinstance(cond, Comparison):
        return _vars_in_expr(cond.left) + _vars_in_expr(cond.right)
    if isinstance(cond, BoolOp):
        return _vars_in_condition(cond.left) + _vars_in_condition(cond.right)
    return []


def _assigned_by(stmt: Statement) -> List[str]:
    """Variables written to by *stmt* (one level deep — no recursion into IF)."""
    if isinstance(stmt, (MoveStmt,)):       return list(stmt.targets)
    if isinstance(stmt, ComputeStmt):       return [stmt.target]
    if isinstance(stmt, (AddStmt, SubtractStmt, MultiplyStmt, DivideStmt)):
        return list(stmt.targets)
    return []


def _expr_repr(expr: Expr) -> str:
    if isinstance(expr, Literal):    return expr.value
    if isinstance(expr, VarRef):     return expr.name
    if isinstance(expr, BinOp):      return f"{_expr_repr(expr.left)}{expr.op}{_expr_repr(expr.right)}"
    if isinstance(expr, UnaryMinus): return f"-{_expr_repr(expr.operand)}"
    return "?"


# ── Reporting ─────────────────────────────────────────────────────────────────

def dfg_summary(G: nx.DiGraph) -> str:
    """Human-readable DFG report (returned as a string)."""
    import re
    lines: List[str] = []

    def py_name(n: str) -> str:
        n = re.sub(r"^WS-", "", n)
        return n.replace("-", "_").lower()

    lines.append("\n  Variables (node  →  Python name  |  PIC  |  in° / out°  |  role)")
    lines.append("  " + "-" * 72)
    for node in sorted(G.nodes()):
        attrs = G.nodes[node]
        if attrs.get("type") == "literal":
            continue
        in_d  = G.in_degree(node)
        out_d = G.out_degree(node)
        if in_d == 0 and out_d > 0:
            role = "SOURCE/INPUT"
        elif out_d == 0 and in_d > 0:
            role = "SINK/OUTPUT"
        elif in_d > 0 and out_d > 0:
            role = "INTERMEDIATE"
        else:
            role = "ISOLATED"
        pic = attrs.get("pic") or "(group)"
        lines.append(
            f"  {node:<28}→ {py_name(node):<22} PIC {pic:<14}"
            f"  in={in_d} out={out_d}  [{role}]"
        )

    lines.append("\n  Data-flow edges (source  →  target  via  op @ paragraph)")
    lines.append("  " + "-" * 72)
    for src, dst, data in sorted(G.edges(data=True), key=lambda e: (e[2].get("line", 0))):
        op   = data.get("op", "?")
        para = data.get("paragraph", "?")
        line = data.get("line", "?")
        branch = data.get("branch")
        branch_str = f" [{branch}]" if branch else ""
        lines.append(f"  L{line:<4} {src:<28}→ {dst:<28} {op} @ {para}{branch_str}")

    return "\n".join(lines)
