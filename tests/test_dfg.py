"""Data Flow Graph builder tests.

The DFG is the Intermediate Representation that feeds the LangGraph
pipeline.  Every node is a variable; every edge is a data dependency.
If the DFG is wrong, the AI's scope-elimination and OOP refactoring
will be structurally incorrect regardless of how good the prompt is.

These tests verify:
  - All WORKING-STORAGE variables become DFG nodes with correct attributes
  - Each statement type produces the correct edge(s) with correct metadata
  - IF conditions create control-dependency edges to all assigned variables
  - Branch labels ('then'/'else') are annotated on edges inside IF blocks
  - Source / Sink / Intermediate roles are derivable from in/out degrees
"""
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import networkx as nx
from tests.helpers import parse_program, make_full_program, tokenize
from pybold.parser.cobol_parser import CobolParser
from pybold.graph.dfg_builder import build_dfg


# ── Helpers ───────────────────────────────────────────────────────────────────

def dfg_from_ws_and_proc(ws_lines: str, proc_lines: str) -> nx.DiGraph:
    prog = parse_program(make_full_program(ws_lines=ws_lines, proc_lines=proc_lines))
    return build_dfg(prog)


def edges_of(G: nx.DiGraph) -> list[tuple]:
    """Return (src, dst, op) triples, sorted for stable comparison."""
    return sorted(
        (s, d, data["op"]) for s, d, data in G.edges(data=True)
        if "op" in data
    )


# ── Node registration ─────────────────────────────────────────────────────────

class TestNodeRegistration:
    def test_all_ws_variables_become_nodes(self):
        ws = (
            "       01 WS-A PIC 9(2) VALUE 0.\n"
            "       01 WS-B PIC 9(2) VALUE 0.\n"
            "       01 WS-C PIC X VALUE 'N'.\n"
        )
        G = dfg_from_ws_and_proc(ws, "")
        assert "WS-A" in G
        assert "WS-B" in G
        assert "WS-C" in G

    def test_node_type_attribute_is_variable(self):
        ws = "       01 WS-A PIC 9(2) VALUE 0.\n"
        G = dfg_from_ws_and_proc(ws, "")
        assert G.nodes["WS-A"]["type"] == "variable"

    def test_node_pic_attribute_preserved(self):
        ws = "       01 WS-AMT PIC 9(7)V99 VALUE 0.\n"
        G = dfg_from_ws_and_proc(ws, "")
        assert G.nodes["WS-AMT"]["pic"] == "9(7)V99"

    def test_node_level_attribute(self):
        ws = "       01 WS-A PIC 9(2) VALUE 0.\n"
        G = dfg_from_ws_and_proc(ws, "")
        assert G.nodes["WS-A"]["level"] == 1

    def test_undeclared_variable_gets_undeclared_node(self):
        """A variable used in PROCEDURE but absent from WORKING-STORAGE
        must still appear as a node (type='undeclared') rather than crashing."""
        G = dfg_from_ws_and_proc(
            "",
            "           MOVE 0 TO WS-MYSTERY."
        )
        assert "WS-MYSTERY" in G
        assert G.nodes["WS-MYSTERY"]["type"] == "undeclared"


# ── MOVE edges ────────────────────────────────────────────────────────────────

class TestMoveEdges:
    def test_move_variable_creates_edge(self):
        ws = (
            "       01 WS-A PIC 9(2) VALUE 0.\n"
            "       01 WS-B PIC 9(2) VALUE 0.\n"
        )
        G = dfg_from_ws_and_proc(ws, "           MOVE WS-A TO WS-B.")
        assert G.has_edge("WS-A", "WS-B")
        assert G["WS-A"]["WS-B"]["op"] == "MOVE"

    def test_move_literal_creates_literal_node(self):
        ws = "       01 WS-X PIC 9(6) VALUE 0.\n"
        G = dfg_from_ws_and_proc(ws, "           MOVE 100423 TO WS-X.")
        lit_node = "LITERAL:100423"
        assert lit_node in G
        assert G.nodes[lit_node]["type"] == "literal"
        assert G.has_edge(lit_node, "WS-X")

    def test_move_multi_target_creates_multiple_edges(self):
        ws = (
            "       01 WS-A PIC 9(2) VALUE 0.\n"
            "       01 WS-B PIC 9(2) VALUE 0.\n"
            "       01 WS-C PIC 9(2) VALUE 0.\n"
        )
        G = dfg_from_ws_and_proc(
            ws,
            "           MOVE 0 TO WS-A WS-B WS-C."
        )
        lit = "LITERAL:0"
        assert G.has_edge(lit, "WS-A")
        assert G.has_edge(lit, "WS-B")
        assert G.has_edge(lit, "WS-C")

    def test_move_edge_carries_paragraph_name(self):
        ws = (
            "       01 WS-A PIC 9(2) VALUE 0.\n"
            "       01 WS-B PIC 9(2) VALUE 0.\n"
        )
        G = dfg_from_ws_and_proc(ws, "           MOVE WS-A TO WS-B.")
        assert G["WS-A"]["WS-B"]["paragraph"] == "TEST-PARA"


# ── COMPUTE edges ─────────────────────────────────────────────────────────────

class TestComputeEdges:
    def test_compute_variable_source_creates_edge(self):
        ws = (
            "       01 WS-A PIC 9(2) VALUE 0.\n"
            "       01 WS-B PIC 9(2) VALUE 0.\n"
        )
        G = dfg_from_ws_and_proc(ws, "           COMPUTE WS-B = WS-A.")
        assert G.has_edge("WS-A", "WS-B")
        assert G["WS-A"]["WS-B"]["op"] == "COMPUTE"

    def test_compute_multi_variable_expression_creates_multiple_edges(self):
        """COMPUTE X = A * B → edges A→X and B→X."""
        ws = (
            "       01 WS-A PIC 9(2) VALUE 0.\n"
            "       01 WS-B PIC 9(2) VALUE 0.\n"
            "       01 WS-X PIC 9(4) VALUE 0.\n"
        )
        G = dfg_from_ws_and_proc(
            ws,
            "           COMPUTE WS-X = WS-A * WS-B."
        )
        assert G.has_edge("WS-A", "WS-X")
        assert G.has_edge("WS-B", "WS-X")

    def test_compute_literal_only_no_variable_edges(self):
        """COMPUTE X = 15 — no variable sources, so no variable→X edges."""
        ws = "       01 WS-X PIC 9(2) VALUE 0.\n"
        G = dfg_from_ws_and_proc(ws, "           COMPUTE WS-X = 15.")
        # No variable-to-variable edges should exist
        var_edges = [
            (s, d) for s, d in G.edges()
            if G.nodes[s].get("type") == "variable"
        ]
        assert var_edges == []


# ── IF condition dependency edges ─────────────────────────────────────────────

class TestIfConditionEdges:
    def test_condition_variable_linked_to_then_assigned(self):
        """
        The variable tested in an IF condition controls which branch runs.
        The DFG must record this as a control-dependency edge:
          WS-AMT  →  WS-FLAG  (op=IF-CONDITION)
        This is critical for the Refactoring Agent to know that WS-FLAG's
        value is conditional on WS-AMT — they must be in the same scope.
        """
        ws = (
            "       01 WS-AMT PIC 9(7)V99 VALUE 0.\n"
            "       01 WS-FLAG PIC X VALUE 'N'.\n"
        )
        G = dfg_from_ws_and_proc(
            ws,
            "           IF WS-AMT > 1000\n"
            "               MOVE 'Y' TO WS-FLAG\n"
            "           END-IF."
        )
        # Control dependency: WS-AMT → WS-FLAG via IF-CONDITION
        assert G.has_edge("WS-AMT", "WS-FLAG")
        assert G["WS-AMT"]["WS-FLAG"]["op"] == "IF-CONDITION"

    def test_then_branch_edge_has_then_label(self):
        ws = (
            "       01 WS-A PIC 9(2) VALUE 0.\n"
            "       01 WS-B PIC 9(2) VALUE 0.\n"
        )
        G = dfg_from_ws_and_proc(
            ws,
            "           IF WS-A > 0\n"
            "               MOVE WS-A TO WS-B\n"
            "           END-IF."
        )
        assert G["WS-A"]["WS-B"]["branch"] == "then"

    def test_else_branch_edge_has_else_label(self):
        ws = (
            "       01 WS-A PIC 9(2) VALUE 0.\n"
            "       01 WS-B PIC 9(2) VALUE 0.\n"
            "       01 WS-C PIC 9(2) VALUE 0.\n"
        )
        G = dfg_from_ws_and_proc(
            ws,
            "           IF WS-A > 0\n"
            "               MOVE WS-A TO WS-B\n"
            "           ELSE\n"
            "               MOVE WS-A TO WS-C\n"
            "           END-IF."
        )
        assert G["WS-A"]["WS-C"]["branch"] == "else"

    def test_non_if_edges_have_no_branch_label(self):
        ws = (
            "       01 WS-A PIC 9(2) VALUE 0.\n"
            "       01 WS-B PIC 9(2) VALUE 0.\n"
        )
        G = dfg_from_ws_and_proc(ws, "           MOVE WS-A TO WS-B.")
        assert G["WS-A"]["WS-B"].get("branch") is None


# ── Node roles (source / sink / intermediate) ─────────────────────────────────

class TestNodeRoles:
    def _roles(self, G: nx.DiGraph) -> dict[str, str]:
        roles = {}
        for n in G.nodes():
            if G.nodes[n].get("type") == "literal":
                continue
            in_d, out_d = G.in_degree(n), G.out_degree(n)
            if in_d == 0 and out_d > 0:
                roles[n] = "SOURCE"
            elif out_d == 0 and in_d > 0:
                roles[n] = "SINK"
            elif in_d > 0 and out_d > 0:
                roles[n] = "INTERMEDIATE"
            else:
                roles[n] = "ISOLATED"
        return roles

    def test_customer_calc_source_sink_roles(self):
        """
        In customer_calc.cbl the discount/final amounts are never read —
        they are SINK nodes.  WS-ORDER-AMT-N feeds everything — INTERMEDIATE
        (it gets written once by MOVE, then read by three COMPUTEs + IF).
        """
        sample = (
            Path(__file__).resolve().parent.parent
            / "samples" / "customer_calc.cbl"
        )
        prog = CobolParser(tokenize(sample.read_text())).parse()
        G = build_dfg(prog)
        roles = self._roles(G)

        # Variables that are only written-to are SINKs
        assert roles["WS-FINAL-AMT-N"] == "SINK"
        assert roles["WS-CUST-ID-X"] == "SINK"

        # WS-ORDER-AMT-N is read by COMPUTE and IF → INTERMEDIATE or SOURCE
        # (it's written by MOVE from literal, so in_degree > 0 → INTERMEDIATE)
        assert roles["WS-ORDER-AMT-N"] in ("INTERMEDIATE", "SOURCE")


# ── Full DFG integration ──────────────────────────────────────────────────────

class TestFullDfgIntegration:
    def test_customer_calc_node_count(self):
        sample = (
            Path(__file__).resolve().parent.parent
            / "samples" / "customer_calc.cbl"
        )
        prog = CobolParser(tokenize(sample.read_text())).parse()
        G = build_dfg(prog)
        # 6 declared variables + 3 literal nodes (100423, 1500.00, 'Y')
        assert G.number_of_nodes() == 9

    def test_customer_calc_edge_count(self):
        sample = (
            Path(__file__).resolve().parent.parent
            / "samples" / "customer_calc.cbl"
        )
        prog = CobolParser(tokenize(sample.read_text())).parse()
        G = build_dfg(prog)
        assert G.number_of_edges() == 9
