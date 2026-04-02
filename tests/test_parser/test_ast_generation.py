"""AST generation tests.

These tests assert on the *typed* AST nodes produced by CobolParser —
not on raw tokens.  They are the primary regression guard for the
neuro-symbolic pipeline: if any of these fail, the LLM receives a
structurally wrong context block and will produce incorrect Python.

The two critical properties locked down here:
  1. PIC clause parsing — the 'maximal munch' fix (TT.LEVEL recovery in
     PIC context) must not regress.
  2. Numeric constant parsing in expressions — the same fix for
     _parse_primary must correctly recover small integers as Literals.
"""
import pytest
from pathlib import Path
from tests.helpers import (
    parse_data, parse_stmts, parse_program, make_full_program,
    DataItem, Literal, VarRef, BinOp, UnaryMinus,
    Comparison, BoolOp,
    MoveStmt, ComputeStmt, AddStmt, SubtractStmt,
    MultiplyStmt, DivideStmt, IfStmt,
    PerformStmt, DisplayStmt, StopRunStmt,
)


# ── DATA DIVISION: PIC clause parsing ────────────────────────────────────────
#
# The 'maximal munch' issue: single digits like '9' (range 1-49) are
# lexed as TT.LEVEL.  _collect_pic_string must recover them via the
# TT.LEVEL branch so the PIC string is captured correctly.

class TestPicParsing:
    def test_pic_integer_9_6(self):
        """PIC 9(6) — the '9' is lexed as LEVEL; must be recovered."""
        items = parse_data("       01 WS-COUNT PIC 9(6) VALUE 0.")
        assert items[0].pic == "9(6)"

    def test_pic_decimal_9_7_v99(self):
        """PIC 9(7)V99 — multiple LEVEL tokens and IDENT 'V'."""
        items = parse_data("       01 WS-AMT PIC 9(7)V99 VALUE 0.")
        assert items[0].pic == "9(7)V99"

    def test_pic_decimal_v_with_repetition(self):
        """PIC 9(3)V99 — common pattern for discount rates."""
        items = parse_data("       01 WS-RATE PIC 9(3)V99 VALUE 0.")
        assert items[0].pic == "9(3)V99"

    def test_pic_alpha_x(self):
        """PIC X — single char alphanumeric; no parentheses."""
        items = parse_data("       01 WS-FLAG PIC X VALUE 'N'.")
        assert items[0].pic == "X"

    def test_pic_alpha_x_with_length(self):
        """PIC X(10) — alphanumeric with explicit length."""
        items = parse_data("       01 WS-NAME PIC X(10).")
        assert items[0].pic == "X(10)"

    def test_pic_star_for_edited(self):
        """PIC Z(7) — Z is an edit char; parsed as IDENT in PIC context."""
        items = parse_data("       01 WS-DISP PIC Z(7).")
        assert items[0].pic == "Z(7)"

    def test_pic_is_keyword_optional(self):
        """PICTURE IS 9(4) — 'IS' is optional and must be silently consumed."""
        items = parse_data("       01 WS-X PIC IS 9(4).")
        assert items[0].pic == "9(4)"

    def test_pic_picture_keyword_synonym(self):
        """PICTURE is a synonym for PIC."""
        items = parse_data("       01 WS-Y PICTURE 9(6) VALUE 0.")
        assert items[0].pic == "9(6)"


class TestDataItemAttributes:
    def test_level_number(self):
        items = parse_data("       01 WS-A PIC 9(2) VALUE 0.")
        assert items[0].level == 1

    def test_name(self):
        items = parse_data("       01 WS-CUST-ID PIC 9(6) VALUE 0.")
        assert items[0].name == "WS-CUST-ID"

    def test_initial_value_integer(self):
        items = parse_data("       01 WS-A PIC 9(2) VALUE 0.")
        assert items[0].initial_value == "0"

    def test_initial_value_string(self):
        items = parse_data("       01 WS-FLAG PIC X VALUE 'N'.")
        assert items[0].initial_value == "'N'"

    def test_multiple_items_order_preserved(self):
        ws = (
            "       01 WS-A PIC 9(2) VALUE 0.\n"
            "       01 WS-B PIC X VALUE 'Y'.\n"
            "       01 WS-C PIC 9(5)V99 VALUE 0.\n"
        )
        items = parse_data(ws)
        assert [i.name for i in items] == ["WS-A", "WS-B", "WS-C"]

    def test_group_item_has_no_pic(self):
        """Group items omit the PIC clause; pic should be empty."""
        ws = (
            "       01 WS-GROUP.\n"
            "          05 WS-CHILD PIC 9(3).\n"
        )
        items = parse_data(ws)
        # The flat list from the parser; group item at index 0
        group = next(i for i in items if i.name == "WS-GROUP")
        assert group.pic == "" or group.pic is None


# ── PROCEDURE DIVISION: numeric literals in expressions ──────────────────────
#
# Same TT.LEVEL ambiguity applies in expression context.  _parse_primary
# must recover small integers (e.g. 15, 5, 100) as Literal nodes.

class TestComputeStatement:
    def test_compute_assigns_to_target(self):
        stmts = parse_stmts("           COMPUTE WS-X = 0.")
        assert isinstance(stmts[0], ComputeStmt)
        assert stmts[0].target == "WS-X"

    def test_compute_small_constant_15(self):
        """15 is in valid level range → lexed as LEVEL; parser must recover it."""
        stmts = parse_stmts("           COMPUTE WS-RATE = 15.")
        assert isinstance(stmts[0], ComputeStmt)
        expr = stmts[0].expression
        assert isinstance(expr, Literal)
        assert expr.value == "15"

    def test_compute_small_constant_5(self):
        stmts = parse_stmts("           COMPUTE WS-RATE = 5.")
        expr = stmts[0].expression
        assert isinstance(expr, Literal)
        assert expr.value == "5"

    def test_compute_large_constant_not_ambiguous(self):
        """1000 is outside level range → lexed as NUMBER; just works."""
        stmts = parse_stmts("           COMPUTE WS-AMT = 1000.")
        expr = stmts[0].expression
        assert isinstance(expr, Literal)
        assert expr.value == "1000"

    def test_compute_variable_reference(self):
        stmts = parse_stmts("           COMPUTE WS-X = WS-Y.")
        expr = stmts[0].expression
        assert isinstance(expr, VarRef)
        assert expr.name == "WS-Y"

    def test_compute_binary_multiply_divide(self):
        """COMPUTE X = A * B / 100 → BinOp(/, BinOp(*, A, B), 100)."""
        stmts = parse_stmts(
            "           COMPUTE WS-DISC = WS-ORDER * WS-RATE / 100."
        )
        expr = stmts[0].expression
        # Outermost op is '/' (left-associative parsing)
        assert isinstance(expr, BinOp)
        assert expr.op == "/"
        # Left operand is A * B
        assert isinstance(expr.left, BinOp)
        assert expr.left.op == "*"
        assert isinstance(expr.left.left, VarRef)
        assert expr.left.left.name == "WS-ORDER"
        assert isinstance(expr.left.right, VarRef)
        assert expr.left.right.name == "WS-RATE"
        # Right operand is 100
        assert isinstance(expr.right, Literal)
        assert expr.right.value == "100"

    def test_compute_additive_expression(self):
        """COMPUTE X = A - B."""
        stmts = parse_stmts(
            "           COMPUTE WS-FINAL = WS-ORDER - WS-DISC."
        )
        expr = stmts[0].expression
        assert isinstance(expr, BinOp)
        assert expr.op == "-"
        assert isinstance(expr.left, VarRef)
        assert expr.left.name == "WS-ORDER"
        assert isinstance(expr.right, VarRef)
        assert expr.right.name == "WS-DISC"


# ── MOVE statement ────────────────────────────────────────────────────────────

class TestMoveStatement:
    def test_move_literal_to_variable(self):
        stmts = parse_stmts("           MOVE 100423 TO WS-CUST-ID.")
        assert isinstance(stmts[0], MoveStmt)
        assert isinstance(stmts[0].source, Literal)
        assert stmts[0].source.value == "100423"
        assert stmts[0].targets == ["WS-CUST-ID"]

    def test_move_string_literal(self):
        stmts = parse_stmts("           MOVE 'Y' TO WS-FLAG.")
        assert isinstance(stmts[0].source, Literal)
        assert stmts[0].source.value == "'Y'"

    def test_move_variable_to_variable(self):
        stmts = parse_stmts("           MOVE WS-A TO WS-B.")
        assert isinstance(stmts[0].source, VarRef)
        assert stmts[0].source.name == "WS-A"
        assert stmts[0].targets == ["WS-B"]

    def test_move_decimal_literal(self):
        stmts = parse_stmts("           MOVE 1500.00 TO WS-ORDER.")
        assert isinstance(stmts[0].source, Literal)
        assert stmts[0].source.value == "1500.00"

    def test_move_multi_target(self):
        """MOVE x TO a b c — all three targets captured."""
        stmts = parse_stmts("           MOVE 0 TO WS-A WS-B WS-C.")
        assert stmts[0].targets == ["WS-A", "WS-B", "WS-C"]


# ── IF statement ──────────────────────────────────────────────────────────────

class TestIfStatement:
    def test_if_produces_if_stmt(self):
        stmts = parse_stmts(
            "           IF WS-AMT > 1000\n"
            "               DISPLAY 'HIGH'\n"
            "           END-IF."
        )
        assert isinstance(stmts[0], IfStmt)

    def test_if_condition_operator_gt(self):
        stmts = parse_stmts(
            "           IF WS-AMT > 1000\n"
            "               DISPLAY 'HI'\n"
            "           END-IF."
        )
        cond = stmts[0].condition
        assert isinstance(cond, Comparison)
        assert cond.op == ">"

    def test_if_condition_left_is_varref(self):
        stmts = parse_stmts(
            "           IF WS-AMT > 1000\n"
            "               DISPLAY 'HI'\n"
            "           END-IF."
        )
        cond = stmts[0].condition
        assert isinstance(cond.left, VarRef)
        assert cond.left.name == "WS-AMT"

    def test_if_condition_right_numeric_constant(self):
        """
        1000 is outside level range so it's NUMBER — but this also validates
        that the condition parser correctly routes right-hand operands through
        _parse_expr which calls _parse_primary.
        """
        stmts = parse_stmts(
            "           IF WS-AMT > 1000\n"
            "               DISPLAY 'HI'\n"
            "           END-IF."
        )
        cond = stmts[0].condition
        assert isinstance(cond.right, Literal)
        assert cond.right.value == "1000"

    def test_if_condition_small_constant(self):
        """IF WS-X > 5 — '5' is LEVEL at lex time; must appear as Literal('5')."""
        stmts = parse_stmts(
            "           IF WS-X > 5\n"
            "               DISPLAY 'HI'\n"
            "           END-IF."
        )
        cond = stmts[0].condition
        assert isinstance(cond.right, Literal)
        assert cond.right.value == "5"

    def test_if_then_branch_populated(self):
        stmts = parse_stmts(
            "           IF WS-AMT > 1000\n"
            "               MOVE 'Y' TO WS-FLAG\n"
            "               COMPUTE WS-RATE = 15\n"
            "           END-IF."
        )
        then = stmts[0].then_stmts
        assert len(then) == 2
        assert isinstance(then[0], MoveStmt)
        assert isinstance(then[1], ComputeStmt)

    def test_if_else_branch_populated(self):
        stmts = parse_stmts(
            "           IF WS-AMT > 1000\n"
            "               COMPUTE WS-RATE = 15\n"
            "           ELSE\n"
            "               COMPUTE WS-RATE = 5\n"
            "           END-IF."
        )
        then_expr = stmts[0].then_stmts[0].expression
        else_expr = stmts[0].else_stmts[0].expression
        assert isinstance(then_expr, Literal) and then_expr.value == "15"
        assert isinstance(else_expr, Literal) and else_expr.value == "5"

    def test_if_no_else_gives_empty_list(self):
        stmts = parse_stmts(
            "           IF WS-X > 0\n"
            "               DISPLAY 'OK'\n"
            "           END-IF."
        )
        assert stmts[0].else_stmts == []

    def test_if_lte_operator(self):
        stmts = parse_stmts(
            "           IF WS-X <= 100\n"
            "               DISPLAY 'LOW'\n"
            "           END-IF."
        )
        assert stmts[0].condition.op == "<="

    def test_if_eq_operator(self):
        stmts = parse_stmts(
            "           IF WS-FLAG = 'Y'\n"
            "               DISPLAY 'YES'\n"
            "           END-IF."
        )
        assert stmts[0].condition.op == "="


# ── Arithmetic statements ─────────────────────────────────────────────────────

class TestArithmeticStatements:
    def test_add_to(self):
        stmts = parse_stmts("           ADD 150 TO WS-TOTAL.")
        assert isinstance(stmts[0], AddStmt)
        assert stmts[0].targets == ["WS-TOTAL"]
        assert isinstance(stmts[0].operands[0], Literal)

    def test_subtract_from(self):
        stmts = parse_stmts("           SUBTRACT WS-DISC FROM WS-AMT.")
        assert isinstance(stmts[0], SubtractStmt)
        assert stmts[0].targets == ["WS-AMT"]
        assert isinstance(stmts[0].subtrahends[0], VarRef)
        assert stmts[0].subtrahends[0].name == "WS-DISC"

    def test_multiply_by(self):
        stmts = parse_stmts("           MULTIPLY 2 BY WS-QTY.")
        assert isinstance(stmts[0], MultiplyStmt)
        assert stmts[0].targets == ["WS-QTY"]
        assert isinstance(stmts[0].operand, Literal)

    def test_divide_into(self):
        stmts = parse_stmts("           DIVIDE 100 INTO WS-RATE.")
        assert isinstance(stmts[0], DivideStmt)
        assert stmts[0].targets == ["WS-RATE"]
        assert isinstance(stmts[0].divisor, Literal)


# ── Other statements ──────────────────────────────────────────────────────────

class TestOtherStatements:
    def test_perform(self):
        stmts = parse_stmts("           PERFORM CALC-ROUTINE.")
        assert isinstance(stmts[0], PerformStmt)
        assert stmts[0].paragraph == "CALC-ROUTINE"

    def test_display_string_and_variable(self):
        stmts = parse_stmts(
            "           DISPLAY 'AMOUNT: ' WS-FINAL."
        )
        assert isinstance(stmts[0], DisplayStmt)
        items = stmts[0].items
        assert len(items) == 2
        assert isinstance(items[0], Literal)
        assert items[0].value == "'AMOUNT: '"
        assert isinstance(items[1], VarRef)
        assert items[1].name == "WS-FINAL"

    def test_stop_run(self):
        source = make_full_program(proc_lines="           STOP RUN.")
        prog = parse_program(source)
        stmts = prog.paragraphs[0].statements
        assert any(isinstance(s, StopRunStmt) for s in stmts)


# ── Full program integration ──────────────────────────────────────────────────

class TestFullProgram:
    def test_customer_calc_sample_parses_without_error(self):
        """Smoke test: the canonical sample file must parse end-to-end."""
        sample = (
            Path(__file__).resolve().parent.parent.parent
            / "samples" / "customer_calc.cbl"
        )
        from tests.helpers import tokenize
        from pybold.parser.cobol_parser import CobolParser
        prog = CobolParser(tokenize(sample.read_text())).parse()
        assert prog.program_id == "CUSTOMER-CALC"

    def test_customer_calc_six_variables(self):
        sample = (
            Path(__file__).resolve().parent.parent.parent
            / "samples" / "customer_calc.cbl"
        )
        from tests.helpers import tokenize
        from pybold.parser.cobol_parser import CobolParser
        prog = CobolParser(tokenize(sample.read_text())).parse()
        assert len(prog.data_items) == 6

    def test_customer_calc_pic_types_correct(self):
        """Regression: PIC strings must not be empty after the maximal-munch fix."""
        sample = (
            Path(__file__).resolve().parent.parent.parent
            / "samples" / "customer_calc.cbl"
        )
        from tests.helpers import tokenize
        from pybold.parser.cobol_parser import CobolParser
        prog = CobolParser(tokenize(sample.read_text())).parse()
        pics = {item.name: item.pic for item in prog.data_items}
        assert pics["WS-CUST-ID-X"] == "9(6)"
        assert pics["WS-ORDER-AMT-N"] == "9(7)V99"
        assert pics["WS-DISCOUNT-RT-N"] == "9(3)V99"
        assert pics["WS-PREMIUM-FLAG-X"] == "X"

    def test_customer_calc_if_branches_correct(self):
        """Regression: COMPUTE constants 15 and 5 must not silently become 0."""
        sample = (
            Path(__file__).resolve().parent.parent.parent
            / "samples" / "customer_calc.cbl"
        )
        from tests.helpers import tokenize
        from pybold.parser.cobol_parser import CobolParser
        prog = CobolParser(tokenize(sample.read_text())).parse()
        # Find the IF statement in MAIN-LOGIC
        para = prog.paragraphs[0]
        if_stmt = next(s for s in para.statements if isinstance(s, IfStmt))
        then_compute: ComputeStmt = if_stmt.then_stmts[1]  # second stmt in THEN
        else_compute: ComputeStmt = if_stmt.else_stmts[0]
        assert isinstance(then_compute.expression, Literal)
        assert then_compute.expression.value == "15"
        assert isinstance(else_compute.expression, Literal)
        assert else_compute.expression.value == "5"

    def test_customer_calc_one_paragraph(self):
        sample = (
            Path(__file__).resolve().parent.parent.parent
            / "samples" / "customer_calc.cbl"
        )
        from tests.helpers import tokenize
        from pybold.parser.cobol_parser import CobolParser
        prog = CobolParser(tokenize(sample.read_text())).parse()
        assert len(prog.paragraphs) == 1
        assert prog.paragraphs[0].name == "MAIN-LOGIC"
