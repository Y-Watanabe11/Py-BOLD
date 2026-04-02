"""Py-BOLD — LangGraph Translation Workflow.

Architecture
------------
LangGraph manages the multi-agent state machine.  Each node is a pure
function: (TranslationState) → dict of updated keys.  The SDK's
StateGraph merges the returned dict back into the shared state, so
nodes only need to return the keys they modified.

Current graph (Phase 4 — full pipeline):

    START ──► structural_agent
          ──► semantic_agent
          ──► verification_agent
          ──► END

Neuro-symbolic boundary
-----------------------
Raw COBOL source is intentionally absent from TranslationState.
Each agent operates on a progressively more Pythonic representation:

  Compiler layer      →  ast_block        (deterministic, structured)
  Structural Agent    →  python_code      (correct but ugly Py-BOL)
  Semantic Agent      →  refactored_code  (correct + readable Python)
  Verification Agent  →  test_code        (pytest suite from AST spec)

LLM configuration
-----------------
- Model   : claude-opus-4-6
- Thinking : adaptive (model decides when/how much to reason privately)
- Streaming: yes (real-time token display + avoids HTTP timeouts)
"""
from __future__ import annotations

import textwrap
from typing import TypedDict

import anthropic
from langgraph.graph import StateGraph, END


# ── State ─────────────────────────────────────────────────────────────────────

class TranslationState(TypedDict):
    """Shared state that flows through every node in the graph.

    Boundary rule: raw COBOL source is intentionally absent.
    The ast_block is the only LLM-visible representation of the original
    program — enforcing the neuro-symbolic contract at the data layer.
    """
    program_id:      str   # e.g. "CUSTOMER-CALC" — used for class naming
    ast_block:       str   # structured output from ast_printer; input to structural_agent
    python_code:     str   # Py-BOL output from structural_agent; input to semantic_agent
    refactored_code: str   # clean Python from semantic_agent; input to verification_agent
    test_code:       str   # pytest suite from verification_agent; proves behavioural parity


# ── Helper ────────────────────────────────────────────────────────────────────

def _stream_agent(
    *,
    label: str,
    system: str,
    user_content: str,
    max_tokens: int = 8192,
) -> str:
    """Call claude-opus-4-6 with streaming + adaptive thinking.

    Returns the full text response.  Prints non-thinking tokens in real
    time so the PoC terminal shows live progress.

    Adaptive thinking note: thinking blocks are suppressed from the
    terminal output — they are the model's private scratchpad.  The text
    block that follows is the verified, committed answer.
    """
    client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from env

    print(f"\n  [{label}] streaming from claude-opus-4-6...\n")
    print("  " + "─" * 58)

    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        _in_thinking = False
        for event in stream:
            if event.type == "content_block_start":
                _in_thinking = (event.content_block.type == "thinking")
            elif (
                event.type == "content_block_delta"
                and not _in_thinking
                and event.delta.type == "text_delta"
            ):
                print(event.delta.text, end="", flush=True)

        final = stream.get_final_message()

    print("\n  " + "─" * 58)

    return next(b.text for b in final.content if b.type == "text").strip()


# ── System prompts ────────────────────────────────────────────────────────────

_STRUCTURAL_SYSTEM = textwrap.dedent("""\
    You are the Structural Agent in the Py-BOLD transpiler pipeline.

    You receive a structured AST dump of a legacy COBOL program.
    This dump is your ONLY input — you do NOT have access to the
    original COBOL source.

    TASK
    ────
    Produce a single, self-contained Python script that is functionally
    equivalent to the program described in the AST.

    OUTPUT STRUCTURE
    ────────────────
    1. Imports — include only what the code needs:
       • `from decimal import Decimal`  when any variable is annotated
         "→ Python Decimal" in the AST.
       • `from dataclasses import dataclass, field`  always.

    2. A single @dataclass class named in PascalCase from the PROGRAM ID
       (e.g. CUSTOMER-CALC → CustomerCalc):
       • Declare each WORKING-STORAGE variable as a typed dataclass field:
           "→ Python int"     →  field_name: int = 0
           "→ Python Decimal" →  field_name: Decimal = Decimal("0")
           "→ Python str"     →  field_name: str = "<init_value_from_AST>"
       • Convert COBOL names to snake_case ONLY.
           WS-CUST-ID-X → ws_cust_id_x
       • Do NOT rename variables semantically — that is the next agent's job.

    3. One method per PARAGRAPH, named in snake_case:
       • MOVE <literal> TO <var>       → self.<var> = <literal>
       • MOVE <var1> TO <var2>         → self.<var2> = self.<var1>
       • COMPUTE <var> = <expr>        → self.<var> = <expr>
         (prefix every variable reference with self.)
       • ADD <x> TO <var>              → self.<var> += <x>
       • SUBTRACT <x> FROM <var>       → self.<var> -= <x>
       • IF <cond> ... ELSE ... END-IF → standard Python if/else block
       • DISPLAY <items>               → print(<comma-separated items>)
       • PERFORM <para>                → self.<para_snake_case>()
       • STOP RUN                      → return

    4. A `main()` function that instantiates the class and calls the
       entry paragraph (first PARAGRAPH in the AST).

    5. An `if __name__ == "__main__": main()` guard.

    STRICT RULES
    ────────────
    • Return ONLY the Python code.  No markdown fences, no explanations.
    • Do not add error handling or validation not present in the AST.
    • Do not add docstrings or comments.
    • Do not invent logic not present in the AST.
    • Decimal arithmetic: use Decimal instances throughout, not floats.
    • Numeric literals assigned to Decimal fields must use string form:
        self.ws_order_amt_n = Decimal("1500.00")   ✓
        self.ws_order_amt_n = 1500.00              ✗
""")

_VERIFICATION_SYSTEM = textwrap.dedent("""\
    You are the Verification Agent in the Py-BOLD transpiler pipeline.

    You receive two inputs:
      1. AST_BLOCK — a structured dump of the original COBOL program.
         This is the AUTHORITATIVE behavioural specification.
         Every variable initial value, every IF branch, every COMPUTE
         expression, every DISPLAY output must be faithfully reproduced.
      2. REFACTORED_CODE — the modernised Python produced by the previous
         agents.  Use this to discover the exact class name, method names,
         and field names you must reference in your tests.

    TASK
    ────
    Write a self-contained pytest module that proves the refactored Python
    is behaviourally identical to the COBOL specification in the AST_BLOCK.

    OUTPUT STRUCTURE
    ────────────────
    1. Module-level imports:
         import pytest
         from decimal import Decimal
         import io, sys

    2. A helper fixture named `program` that instantiates the refactored
       class and returns it:
         @pytest.fixture
         def program():
             return <ClassName>()

    3. One test function per assertion category:

       a. test_initial_values — verify every dataclass field starts at
          the value shown in the AST_BLOCK (use Decimal("...") for
          Decimal fields, int for int, str for str).

       b. test_<paragraph_name> — one test per PARAGRAPH in the AST.
          Call the paragraph's method, then assert the state of all
          variables that the paragraph modifies.
          • Cover both branches of every IF statement (use separate
            helper calls or parametrize).
          • For DISPLAY statements, capture stdout with
            `capsys.readouterr()` and assert the output contains
            the expected string(s).

       c. test_full_run — call the entry paragraph end-to-end and assert
          all final field values and stdout output for the canonical
          input defined in the AST_BLOCK (i.e. with all default initial
          values).

    4. Import the refactored class at the top of the module.  Derive the
       import from REFACTORED_CODE — look at its filename convention
       (snake_case of the class name) and use:
         from generated_module import <ClassName>

    STRICT RULES
    ────────────
    • Return ONLY the Python code.  No markdown fences, no explanations.
    • Do not import the original COBOL or the Structural Agent output.
    • Every assert must include a descriptive failure message:
        assert program.field == expected, "field should be X after Y"
    • Use Decimal string literals for Decimal assertions:
        assert program.discount_amount == Decimal("150.00"), "..."
    • Do not add docstrings or comments beyond what is shown above.
    • If a DISPLAY produces multiple items separated by spaces, assert
      each item appears in the captured output.
    • Parametrize IF-branch tests only when the branch condition is
      driven by a single input variable; otherwise write separate tests.
""")

_SEMANTIC_SYSTEM = textwrap.dedent("""\
    You are the Semantic Agent in the Py-BOLD transpiler pipeline.

    You receive a structurally correct Python script produced by the
    Structural Agent.  The logic is verified and must not change.
    The variable names are COBOL artefacts and must be replaced.

    TASK
    ────
    Rename identifiers to reveal the business intent hidden behind the
    COBOL naming conventions.  The refactored code must be identical in
    behaviour — only names change.

    COBOL NAMING CONVENTIONS (to decode)
    ─────────────────────────────────────
    Prefix  WS-       : Working-Storage (local state)  → strip the prefix
    Suffix  -X or -XY : alphanumeric / string field    → name the concept
    Suffix  -N or -NY : numeric / Decimal field        → name the concept
    Suffix  -FLAG      : boolean-like indicator        → use is_<concept>
    Compound names     : WS-ORDER-AMT-N → order_amount (Decimal)
                         WS-CUST-ID-X   → customer_id  (int)
                         WS-DISCOUNT-RT-N → discount_rate (Decimal)
                         WS-PREMIUM-FLAG-X → is_premium (str, 'Y'/'N')

    RENAMING RULES
    ──────────────
    1. Rename every dataclass field, method parameter, and local variable.
    2. Rename the class to reflect the program's business purpose.
       Example: CustomerCalc → CustomerDiscountCalculator
    3. Update every usage site (self.<old> → self.<new>).
    4. Keep names lowercase_with_underscores (PEP 8).
    5. Prefer domain vocabulary over technical vocabulary:
         ws_discount_amt_n  → discount_amount   (not discounted_n)
         ws_final_amt_n     → final_amount      (not total_final)

    WHAT NOT TO CHANGE
    ──────────────────
    • Logic, arithmetic, control flow, comparisons — must stay identical.
    • Imports — keep exactly as-is.
    • String literals (e.g. 'Y', 'CUSTOMER: ') — do not translate.
    • Numeric literals and Decimal("...") calls — do not alter.
    • The main() function structure.

    STRICT RULES
    ────────────
    • Return ONLY the Python code.  No markdown fences, no explanations.
    • Do not add docstrings, comments, or type annotations beyond what exists.
    • Do not add, remove, or reorder any statements.
    • If a name's meaning is genuinely ambiguous, keep the snake_case
      version of the COBOL name rather than guessing.
""")


# ── Nodes ─────────────────────────────────────────────────────────────────────

def structural_agent(state: TranslationState) -> dict:
    """LangGraph node — AST block → structurally correct Py-BOL Python.

    The model is constrained to mechanical translation: COBOL constructs
    map 1:1 to Python equivalents, variable names are snake_cased but
    otherwise unchanged.  Correctness is verifiable against the AST.
    """
    python_code = _stream_agent(
        label="structural_agent",
        system=_STRUCTURAL_SYSTEM,
        user_content=(
            f"PROGRAM ID: {state['program_id']}\n\n"
            f"{state['ast_block']}"
        ),
    )
    return {"python_code": python_code}


def semantic_agent(state: TranslationState) -> dict:
    """LangGraph node — Py-BOL Python → clean, readable Python.

    Receives the Structural Agent's output (correct but ugly) and
    applies semantic renaming.  The business logic is never re-derived
    from COBOL — the agent works purely on Python-to-Python refactoring,
    so any hallucination would produce a TypeError or NameError, making
    correctness failures immediately detectable.
    """
    refactored_code = _stream_agent(
        label="semantic_agent",
        system=_SEMANTIC_SYSTEM,
        user_content=state["python_code"],
    )
    return {"refactored_code": refactored_code}


def verification_agent(state: TranslationState) -> dict:
    """LangGraph node — AST spec + refactored Python → pytest suite.

    The AST block is the ground truth for behaviour (branch conditions,
    initial values, DISPLAY outputs).  The refactored code supplies the
    exact class and method names so generated tests are immediately
    runnable without any manual editing.

    Raw COBOL never enters this node — the neuro-symbolic boundary holds.
    """
    test_code = _stream_agent(
        label="verification_agent",
        system=_VERIFICATION_SYSTEM,
        user_content=(
            f"[AST_BLOCK]\n{state['ast_block']}\n[/AST_BLOCK]\n\n"
            f"[REFACTORED_CODE]\n{state['refactored_code']}\n[/REFACTORED_CODE]"
        ),
        max_tokens=16384,
    )
    return {"test_code": test_code}


# ── Graph factory ─────────────────────────────────────────────────────────────

def build_translation_graph():
    """Compile and return the LangGraph multi-agent workflow."""
    workflow = StateGraph(TranslationState)

    workflow.add_node("structural_agent",   structural_agent)
    workflow.add_node("semantic_agent",     semantic_agent)
    workflow.add_node("verification_agent", verification_agent)

    workflow.set_entry_point("structural_agent")
    workflow.add_edge("structural_agent",   "semantic_agent")
    workflow.add_edge("semantic_agent",     "verification_agent")
    workflow.add_edge("verification_agent", END)

    return workflow.compile()
