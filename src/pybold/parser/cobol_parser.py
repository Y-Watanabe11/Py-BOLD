"""Recursive-descent parser for the Py-BOLD COBOL subset.

Grammar coverage:
  IDENTIFICATION DIVISION  →  PROGRAM-ID
  DATA DIVISION            →  WORKING-STORAGE SECTION (01–49, 66, 77 levels)
  PROCEDURE DIVISION       →  paragraphs containing
                               MOVE, COMPUTE, ADD, SUBTRACT,
                               MULTIPLY, DIVIDE, IF/ELSE/END-IF,
                               PERFORM, DISPLAY, STOP RUN
"""
from __future__ import annotations
from typing import List, Optional

from .lexer import TT, Token, tokenize
from .ast_nodes import (
    CobolProgram, DataItem, Paragraph,
    Statement, Expr, Condition,
    Literal, VarRef, BinOp, UnaryMinus,
    Comparison, BoolOp,
    MoveStmt, ComputeStmt, AddStmt, SubtractStmt,
    MultiplyStmt, DivideStmt, IfStmt,
    PerformStmt, DisplayStmt, StopRunStmt,
)


class ParseError(Exception):
    pass


# Token types that can start a statement
_STMT_STARTERS = frozenset({
    TT.MOVE, TT.COMPUTE, TT.ADD, TT.SUBTRACT, TT.MULTIPLY, TT.DIVIDE,
    TT.IF, TT.PERFORM, TT.DISPLAY, TT.STOP,
})

# Token types that are valid inside a PIC string.
# TT.LEVEL is included because single digits like '9' in "PIC 9(6)" are
# lexed as LEVEL tokens (9 ∈ valid level range 1–49) — we recover the raw
# digit in _collect_pic_string by stripping the zero-pad.
_PIC_TOKENS = frozenset({TT.IDENT, TT.NUMBER, TT.LEVEL, TT.LPAREN, TT.RPAREN, TT.STAR})


class CobolParser:
    def __init__(self, tokens: List[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    # ── Token navigation ──────────────────────────────────────────────────────

    def _cur(self) -> Token:
        return self._tokens[self._pos]

    def _peek(self, offset: int = 1) -> Token:
        idx = min(self._pos + offset, len(self._tokens) - 1)
        return self._tokens[idx]

    def _advance(self) -> Token:
        t = self._tokens[self._pos]
        if t.type != TT.EOF:
            self._pos += 1
        return t

    def _match(self, *types: TT) -> bool:
        return self._cur().type in types

    def _consume_if(self, *types: TT) -> Optional[Token]:
        if self._match(*types):
            return self._advance()
        return None

    def _expect(self, *types: TT) -> Token:
        t = self._cur()
        if t.type not in types:
            expected = " or ".join(tt.name for tt in types)
            raise ParseError(
                f"Line {t.line}: expected {expected}, got {t.type.name!r} ({t.value!r})"
            )
        return self._advance()

    def _is_paragraph_header(self) -> bool:
        """True when sitting at  IDENT  DOT  (a paragraph-name line)."""
        return self._match(TT.IDENT) and self._peek(1).type == TT.DOT

    # ── Top-level ─────────────────────────────────────────────────────────────

    def parse(self) -> CobolProgram:
        program_id = self._parse_identification_division()
        data_items = self._parse_data_division()
        paragraphs = self._parse_procedure_division()
        return CobolProgram(program_id, data_items, paragraphs)

    # ── IDENTIFICATION DIVISION ───────────────────────────────────────────────

    def _parse_identification_division(self) -> str:
        self._expect(TT.IDENTIFICATION)
        self._expect(TT.DIVISION)
        self._expect(TT.DOT)
        self._expect(TT.PROGRAM_ID)
        self._expect(TT.DOT)
        name = self._expect(TT.IDENT)
        self._expect(TT.DOT)
        return name.value

    # ── DATA DIVISION ─────────────────────────────────────────────────────────

    def _parse_data_division(self) -> List[DataItem]:
        self._expect(TT.DATA)
        self._expect(TT.DIVISION)
        self._expect(TT.DOT)
        self._expect(TT.WORKING_STORAGE)
        self._expect(TT.SECTION)
        self._expect(TT.DOT)

        items: List[DataItem] = []
        while self._match(TT.LEVEL):
            items.append(self._parse_data_item())
        return items

    def _parse_data_item(self) -> DataItem:
        level_tok = self._expect(TT.LEVEL)
        level = int(level_tok.value)
        name_tok = self._expect(TT.IDENT)

        pic: Optional[str] = None
        initial_value: Optional[str] = None

        while not self._match(TT.DOT, TT.EOF):
            if self._match(TT.PIC, TT.PICTURE):
                self._advance()
                self._consume_if(TT.IS)
                pic = self._collect_pic_string()
            elif self._match(TT.VALUE):
                self._advance()
                self._consume_if(TT.IS)
                initial_value = self._collect_value()
            else:
                self._advance()  # skip clauses we don't model (USAGE, SYNC, …)

        self._consume_if(TT.DOT)
        return DataItem(level, name_tok.value, pic, initial_value, level_tok.line)

    def _collect_pic_string(self) -> str:
        """Collect tokens that form a PIC string, e.g. 9(6)V9(2), X(20).

        LEVEL tokens appear here when a PIC digit (9, 1–49) is lexed as a
        level number before the parser gains context.  Strip the zero-pad so
        '09' → '9' and '07' → '7', preserving the canonical PIC form.
        """
        parts: List[str] = []
        while self._cur().type in _PIC_TOKENS:
            tok = self._advance()
            val = str(int(tok.value)) if tok.type == TT.LEVEL else tok.value
            parts.append(val)
        return "".join(parts)

    def _collect_value(self) -> str:
        """Collect one VALUE literal (number, string, or figurative constant)."""
        t = self._cur()
        if t.type in (TT.NUMBER, TT.STRING, TT.IDENT):
            return self._advance().value
        if t.type == TT.MINUS:
            self._advance()
            return "-" + self._advance().value
        return "0"

    # ── PROCEDURE DIVISION ────────────────────────────────────────────────────

    def _parse_procedure_division(self) -> List[Paragraph]:
        self._expect(TT.PROCEDURE)
        self._expect(TT.DIVISION)
        self._expect(TT.DOT)

        paragraphs: List[Paragraph] = []
        while not self._match(TT.EOF):
            paragraphs.append(self._parse_paragraph())
        return paragraphs

    def _parse_paragraph(self) -> Paragraph:
        name_tok = self._expect(TT.IDENT)
        self._expect(TT.DOT)

        stmts: List[Statement] = []
        while not self._match(TT.EOF):
            # A bare  IDENT .  at the start of the next line is a new paragraph
            if self._is_paragraph_header():
                break
            stmt = self._parse_statement()
            if stmt is not None:
                stmts.append(stmt)

        return Paragraph(name_tok.value, stmts, name_tok.line)

    # ── Statements ────────────────────────────────────────────────────────────

    def _parse_statement(self) -> Optional[Statement]:
        t = self._cur()
        if t.type == TT.MOVE:       return self._parse_move()
        if t.type == TT.COMPUTE:    return self._parse_compute()
        if t.type == TT.ADD:        return self._parse_add()
        if t.type == TT.SUBTRACT:   return self._parse_subtract()
        if t.type == TT.MULTIPLY:   return self._parse_multiply()
        if t.type == TT.DIVIDE:     return self._parse_divide()
        if t.type == TT.IF:         return self._parse_if()
        if t.type == TT.PERFORM:    return self._parse_perform()
        if t.type == TT.DISPLAY:    return self._parse_display()
        if t.type == TT.STOP:       return self._parse_stop_run()
        if t.type == TT.DOT:
            self._advance()         # absorb stray period
            return None
        # Unknown token in statement position — skip it
        self._advance()
        return None

    def _parse_move(self) -> MoveStmt:
        line = self._cur().line
        self._expect(TT.MOVE)
        source = self._parse_expr()
        self._expect(TT.TO)
        targets = [self._expect(TT.IDENT).value]
        while self._match(TT.IDENT) and self._peek(1).type != TT.DOT:
            targets.append(self._advance().value)
        # Accept the final IDENT even if followed by DOT (last target before '.')
        if self._match(TT.IDENT):
            targets.append(self._advance().value)
        self._consume_if(TT.DOT)
        return MoveStmt(source, targets, line)

    def _parse_compute(self) -> ComputeStmt:
        line = self._cur().line
        self._expect(TT.COMPUTE)
        target = self._expect(TT.IDENT).value
        self._consume_if(TT.EQ)
        expr = self._parse_expr()
        self._consume_if(TT.DOT)
        return ComputeStmt(target, expr, line)

    def _parse_add(self) -> AddStmt:
        line = self._cur().line
        self._expect(TT.ADD)
        operands: List[Expr] = []
        while not self._match(TT.TO, TT.GIVING, TT.DOT, TT.EOF):
            operands.append(self._parse_primary())
        self._consume_if(TT.TO)
        targets: List[str] = []
        while self._match(TT.IDENT):
            targets.append(self._advance().value)
        if self._match(TT.GIVING):
            self._advance()
            targets = [self._expect(TT.IDENT).value]
        self._consume_if(TT.DOT)
        return AddStmt(operands, targets, line)

    def _parse_subtract(self) -> SubtractStmt:
        line = self._cur().line
        self._expect(TT.SUBTRACT)
        subtrahends: List[Expr] = []
        while not self._match(TT.FROM, TT.DOT, TT.EOF):
            subtrahends.append(self._parse_primary())
        self._consume_if(TT.FROM)
        targets: List[str] = []
        while self._match(TT.IDENT):
            targets.append(self._advance().value)
        if self._match(TT.GIVING):
            self._advance()
            targets = [self._expect(TT.IDENT).value]
        self._consume_if(TT.DOT)
        return SubtractStmt(subtrahends, targets, line)

    def _parse_multiply(self) -> MultiplyStmt:
        line = self._cur().line
        self._expect(TT.MULTIPLY)
        operand = self._parse_primary()
        self._expect(TT.BY)
        targets: List[str] = [self._expect(TT.IDENT).value]
        if self._match(TT.GIVING):
            self._advance()
            targets = [self._expect(TT.IDENT).value]
        self._consume_if(TT.DOT)
        return MultiplyStmt(operand, targets, line)

    def _parse_divide(self) -> DivideStmt:
        line = self._cur().line
        self._expect(TT.DIVIDE)
        divisor = self._parse_primary()
        if self._match(TT.INTO):
            self._advance()
        elif self._match(TT.BY):
            self._advance()
        targets: List[str] = [self._expect(TT.IDENT).value]
        if self._match(TT.GIVING):
            self._advance()
            targets = [self._expect(TT.IDENT).value]
        self._consume_if(TT.DOT)
        return DivideStmt(divisor, targets, line)

    def _parse_if(self) -> IfStmt:
        line = self._cur().line
        self._expect(TT.IF)
        condition = self._parse_condition()
        self._consume_if(TT.THEN)

        then_stmts: List[Statement] = []
        while not self._match(TT.ELSE, TT.END_IF, TT.EOF):
            stmt = self._parse_statement()
            if stmt is not None:
                then_stmts.append(stmt)

        else_stmts: List[Statement] = []
        if self._match(TT.ELSE):
            self._advance()
            while not self._match(TT.END_IF, TT.EOF):
                stmt = self._parse_statement()
                if stmt is not None:
                    else_stmts.append(stmt)

        self._consume_if(TT.END_IF)
        self._consume_if(TT.DOT)
        return IfStmt(condition, then_stmts, else_stmts, line)

    def _parse_perform(self) -> PerformStmt:
        line = self._cur().line
        self._expect(TT.PERFORM)
        para = self._expect(TT.IDENT).value
        self._consume_if(TT.DOT)
        return PerformStmt(para, line)

    def _parse_display(self) -> DisplayStmt:
        line = self._cur().line
        self._expect(TT.DISPLAY)
        items: List[Expr] = []
        while not self._match(TT.DOT, TT.EOF):
            if self._match(TT.STRING, TT.NUMBER):
                items.append(Literal(self._cur().value, self._cur().line))
                self._advance()
            elif self._match(TT.IDENT):
                items.append(VarRef(self._cur().value, self._cur().line))
                self._advance()
            else:
                break
        self._consume_if(TT.DOT)
        return DisplayStmt(items, line)

    def _parse_stop_run(self) -> StopRunStmt:
        line = self._cur().line
        self._expect(TT.STOP)
        self._consume_if(TT.RUN)
        self._consume_if(TT.DOT)
        return StopRunStmt(line)

    # ── Conditions ────────────────────────────────────────────────────────────

    def _parse_condition(self) -> Condition:
        left = self._parse_simple_condition()
        while self._match(TT.AND, TT.OR):
            op = self._advance().value
            right = self._parse_simple_condition()
            left = BoolOp(op, left, right, left.line)  # type: ignore[attr-defined]
        return left

    def _parse_simple_condition(self) -> Condition:
        line = self._cur().line
        negate = False
        if self._match(TT.NOT):
            self._advance()
            negate = True

        left_expr = self._parse_expr()
        op = self._parse_relop()
        if op is None:
            cmp = Comparison("NONZERO", left_expr, Literal("0", line), line)
        else:
            right_expr = self._parse_expr()
            cmp = Comparison(("NOT " + op) if negate else op, left_expr, right_expr, line)
        return cmp

    def _parse_relop(self) -> Optional[str]:
        if self._match(TT.GTE):   self._advance(); return ">="
        if self._match(TT.LTE):   self._advance(); return "<="
        if self._match(TT.GT):    self._advance(); return ">"
        if self._match(TT.LT):    self._advance(); return "<"
        if self._match(TT.EQ):    self._advance(); return "="
        if self._match(TT.GREATER):
            self._advance(); self._consume_if(TT.THAN); return ">"
        if self._match(TT.LESS):
            self._advance(); self._consume_if(TT.THAN); return "<"
        if self._match(TT.EQUAL):
            self._advance(); self._consume_if(TT.TO, TT.IS); return "="
        return None

    # ── Expressions (operator-precedence) ────────────────────────────────────

    def _parse_expr(self) -> Expr:
        return self._parse_add_expr()

    def _parse_add_expr(self) -> Expr:
        left = self._parse_mul_expr()
        while self._match(TT.PLUS, TT.MINUS):
            op = self._advance().value
            right = self._parse_mul_expr()
            left = BinOp(op, left, right, getattr(left, "line", 0))
        return left

    def _parse_mul_expr(self) -> Expr:
        left = self._parse_unary()
        while self._match(TT.STAR, TT.SLASH):
            op = self._advance().value
            right = self._parse_unary()
            left = BinOp(op, left, right, getattr(left, "line", 0))
        return left

    def _parse_unary(self) -> Expr:
        if self._match(TT.MINUS):
            line = self._cur().line
            self._advance()
            return UnaryMinus(self._parse_primary(), line)
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        t = self._cur()
        if t.type == TT.LPAREN:
            self._advance()
            expr = self._parse_expr()
            self._consume_if(TT.RPAREN)
            return expr
        if t.type == TT.NUMBER:
            self._advance()
            return Literal(t.value, t.line)
        if t.type == TT.STRING:
            self._advance()
            return Literal(t.value, t.line)
        if t.type == TT.IDENT:
            self._advance()
            return VarRef(t.value, t.line)
        # A LEVEL token (e.g. 15, 5) appearing in expression context means the
        # lexer classified a small integer as a level number.  Recover it as a
        # plain numeric literal by stripping the zero-pad.
        if t.type == TT.LEVEL:
            self._advance()
            return Literal(str(int(t.value)), t.line)
        # Fallback for unexpected tokens in expression position
        return Literal("0", t.line)


def parse_file(path: str) -> CobolProgram:
    """Convenience: read a .cbl file and return its AST."""
    with open(path, encoding="utf-8") as f:
        source = f.read()
    tokens = tokenize(source)
    return CobolParser(tokens).parse()
