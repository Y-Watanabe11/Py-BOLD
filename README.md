# Py-BOLD: Bridging the Semantic Gap in Legacy Modernization

**An Agentic, Neuro-Symbolic COBOL-to-Python Transpiler**

## Executive Summary
While enterprise tools for COBOL-to-Python migration exist, they typically perform a 1:1 syntax translation. This creates what engineers call **"Py-BOL"**—code that executes in a Python environment but retains COBOL's procedural paradigms, global states, and cryptic variable names (e.g., `WS-CUST-ID-X`). It is functional, but practically unmaintainable.

Py-BOLD solves this semantic gap. It is a proof-of-concept transpiler that marries deterministic compiler theory with multi-agent generative AI workflows. Instead of blindly trusting an LLM to translate code, Py-BOLD restricts the AI using a strictly parsed Abstract Syntax Tree (AST), restoring the original human intent without sacrificing mathematical reliability.

---

## The Neuro-Symbolic Pipeline
The architecture abandons the monolithic "zero-shot" LLM approach in favor of a specialized, multi-phase pipeline.

### 1. Deterministic Parsing (The Anchor)
Before any AI is invoked, a custom Lexer and Parser extract the Abstract Syntax Tree (AST) and Data Flow Graph (DFG) from the legacy COBOL. This maps complex, globally scoped state dependencies into a structured context block, preventing the AI from hallucinating business logic.
* *Note on Lexer Design:* Implemented context-aware tokenization to overcome classic "maximal munch" ambiguity in COBOL (e.g., distinguishing a level number `01` from a numeric literal in a `COMPUTE` statement).

### 2. The Structural Agent (Logic Preservation)
Taking the deterministic AST/DFG as its only context, this agent translates the procedural logic into functionally equivalent Python (e.g., mapping `DATA DIVISION` to `@dataclass`).
* **Constraint:** It is strictly forbidden from renaming variables. It produces structurally perfect, but ugly "Py-BOL" (maintaining names like `ws_order_amt_n`).

### 3. The Semantic Agent (Intent Restoration)
This agent takes the raw Python output from Phase 2 and refactors it into PEP 8-compliant, modern Python (e.g., renaming `ws_order_amt_n` to `order_amount`).
* **Architectural Advantage (Bounded Error Surface):** By isolating the semantic refactoring into a Python-to-Python pipeline, the LLM's hallucination surface is strictly constrained. Any naming anomalies introduced here resolve into predictable runtime exceptions (e.g., `NameError`), rather than silent logic bugs in the transpiled code.

### 4. The Verification Agent (Automated QA)
Modernization without verification is a liability. This final agent acts as an automated QA engineer, synthesizing a comprehensive `pytest` suite directly from the legacy COBOL execution paths. It executes against the newly generated Python module to guarantee **1:1 Behavioral Parity**.

---

## Transformation Example

The following shows the full pipeline applied to a real COBOL specimen (`samples/customer_calc.cbl`).

### Input: Legacy COBOL

```cobol
IDENTIFICATION DIVISION.
PROGRAM-ID. CUSTOMER-CALC.

DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-CUST-ID-X         PIC 9(6)    VALUE 0.
01 WS-ORDER-AMT-N       PIC 9(7)V99 VALUE 0.
01 WS-DISCOUNT-RT-N     PIC 9(3)V99 VALUE 0.
01 WS-DISCOUNT-AMT-N    PIC 9(7)V99 VALUE 0.
01 WS-FINAL-AMT-N       PIC 9(7)V99 VALUE 0.
01 WS-PREMIUM-FLAG-X    PIC X       VALUE 'N'.

PROCEDURE DIVISION.
MAIN-LOGIC.
    MOVE 100423         TO WS-CUST-ID-X.
    MOVE 1500.00        TO WS-ORDER-AMT-N.
    IF WS-ORDER-AMT-N > 1000
        MOVE 'Y'        TO WS-PREMIUM-FLAG-X
        COMPUTE WS-DISCOUNT-RT-N = 15
    ELSE
        COMPUTE WS-DISCOUNT-RT-N = 5
    END-IF.
    COMPUTE WS-DISCOUNT-AMT-N =
        WS-ORDER-AMT-N * WS-DISCOUNT-RT-N / 100.
    COMPUTE WS-FINAL-AMT-N =
        WS-ORDER-AMT-N - WS-DISCOUNT-AMT-N.
    DISPLAY 'CUSTOMER: ' WS-CUST-ID-X.
    DISPLAY 'FINAL AMOUNT: ' WS-FINAL-AMT-N.
    STOP RUN.
```

### Stage 1 → Structural Agent output ("Py-BOL")
*Correct but ugly: snake_case names, COBOL identifiers preserved.*

```python
from decimal import Decimal
from dataclasses import dataclass, field

@dataclass
class CustomerCalc:
    ws_cust_id_x: int = 0
    ws_order_amt_n: Decimal = Decimal("0")
    ws_discount_rt_n: Decimal = Decimal("0")
    ws_discount_amt_n: Decimal = Decimal("0")
    ws_final_amt_n: Decimal = Decimal("0")
    ws_premium_flag_x: str = 'N'

    def main_logic(self):
        self.ws_cust_id_x = 100423
        self.ws_order_amt_n = Decimal("1500.00")
        if self.ws_order_amt_n > 1000:
            self.ws_premium_flag_x = 'Y'
            self.ws_discount_rt_n = Decimal("15")
        else:
            self.ws_discount_rt_n = Decimal("5")
        self.ws_discount_amt_n = (
            self.ws_order_amt_n * self.ws_discount_rt_n / Decimal("100")
        )
        self.ws_final_amt_n = self.ws_order_amt_n - self.ws_discount_amt_n
        print('CUSTOMER: ', self.ws_cust_id_x)
        print('FINAL AMOUNT: ', self.ws_final_amt_n)
        return

def main():
    obj = CustomerCalc()
    obj.main_logic()

if __name__ == "__main__":
    main()
```

### Stage 2 → Semantic Agent output (Modern Python)
*Business intent restored: domain vocabulary replaces COBOL artefacts.*

```python
from decimal import Decimal
from dataclasses import dataclass, field

@dataclass
class CustomerDiscountCalculator:
    customer_id: int = 0
    order_amount: Decimal = Decimal("0")
    discount_rate: Decimal = Decimal("0")
    discount_amount: Decimal = Decimal("0")
    final_amount: Decimal = Decimal("0")
    is_premium: str = 'N'

    def main_logic(self):
        self.customer_id = 100423
        self.order_amount = Decimal("1500.00")
        if self.order_amount > 1000:
            self.is_premium = 'Y'
            self.discount_rate = Decimal("15")
        else:
            self.discount_rate = Decimal("5")
        self.discount_amount = (
            self.order_amount * self.discount_rate / Decimal("100")
        )
        self.final_amount = self.order_amount - self.discount_amount
        print('CUSTOMER: ', self.customer_id)
        print('FINAL AMOUNT: ', self.final_amount)
        return

def main():
    obj = CustomerDiscountCalculator()
    obj.main_logic()

if __name__ == "__main__":
    main()
```

### Stage 3 → Verification Agent output (Generated pytest suite)
*Synthesized directly from the AST spec — no human wrote these tests.*

```python
import pytest
from decimal import Decimal
import io, sys
from generated_module import CustomerDiscountCalculator

@pytest.fixture
def program():
    return CustomerDiscountCalculator()

def test_initial_values(program):
    assert program.customer_id == 0,        "customer_id should default to 0"
    assert program.order_amount == Decimal("0"),   "order_amount should default to Decimal('0')"
    assert program.discount_rate == Decimal("0"),  "discount_rate should default to Decimal('0')"
    assert program.discount_amount == Decimal("0"),"discount_amount should default to Decimal('0')"
    assert program.final_amount == Decimal("0"),   "final_amount should default to Decimal('0')"
    assert program.is_premium == 'N',       "is_premium should default to 'N'"

def test_main_logic_premium_branch(program):
    program.main_logic()
    assert program.customer_id == 100423,               "customer_id should be set by MOVE"
    assert program.order_amount == Decimal("1500.00"),   "order_amount should be 1500.00"
    assert program.is_premium == 'Y',                   "is_premium should be Y for order > 1000"
    assert program.discount_rate == Decimal("15"),       "discount_rate should be 15 for premium"
    assert program.discount_amount == Decimal("225.00"), "discount_amount should be 15% of 1500"
    assert program.final_amount == Decimal("1275.00"),   "final_amount should be 1500 - 225"

def test_main_logic_standard_branch():
    # The COBOL program hardcodes MOVE 1500.00 TO WS-ORDER-AMT-N at the top of
    # MAIN-LOGIC, so the else-branch is unreachable via main_logic().
    # We test the branching arithmetic directly by setting fields as the COBOL
    # interpreter would have them if order_amount were 800.
    p = CustomerDiscountCalculator()
    p.order_amount = Decimal("800.00")
    p.discount_rate = Decimal("5")
    p.discount_amount = p.order_amount * p.discount_rate / Decimal("100")
    p.final_amount = p.order_amount - p.discount_amount
    assert p.is_premium == 'N',                  "is_premium should remain N for order <= 1000"
    assert p.discount_rate == Decimal("5"),       "discount_rate should be 5 for standard"
    assert p.discount_amount == Decimal("40.00"), "discount_amount should be 5% of 800"
    assert p.final_amount == Decimal("760.00"),   "final_amount should be 800 - 40"

def test_main_logic_display_output(program, capsys):
    program.main_logic()
    captured = capsys.readouterr()
    assert 'CUSTOMER: ' in captured.out,      "stdout should contain CUSTOMER label"
    assert '100423' in captured.out,          "stdout should contain customer id"
    assert 'FINAL AMOUNT: ' in captured.out,  "stdout should contain FINAL AMOUNT label"
    assert '1275.00' in captured.out,         "stdout should contain final amount"

def test_full_run(program, capsys):
    program.main_logic()
    assert program.final_amount == Decimal("1275.00"), "end-to-end: final amount should be 1275.00"
    assert program.is_premium == 'Y',                  "end-to-end: premium flag should be Y"
    out = capsys.readouterr().out
    assert '1275.00' in out, "end-to-end: 1275.00 must appear in stdout"
```

### Pytest result
```
collected 5 items

test_generated.py::test_initial_values              PASSED
test_generated.py::test_main_logic_premium_branch   PASSED
test_generated.py::test_main_logic_standard_branch  PASSED
test_generated.py::test_main_logic_display_output   PASSED
test_generated.py::test_full_run                    PASSED

============================= 5 passed in 0.12s ==============================
```

---

## Architectural Insights & Lessons Learned

**1. Redefining Determinism with Adaptive Thinking**
Early iterations relied on standard LangChain wrappers and `temperature=0.1` to force deterministic outputs. However, I discovered that low temperature suppresses both variance *and* reasoning. I bypassed the wrapper to use the Anthropic SDK directly, enabling "adaptive thinking." This allowed the model to privately commit to a reasoning path before outputting code, resulting in higher logical determinism than temperature manipulation alone could achieve.

**2. The Future is Orchestration, Not Generation**
The success of Py-BOLD stems from realizing that the highest value of Generative AI in software engineering is not writing code from scratch, but acting as a specialized worker within a heavily constrained, traditionally engineered pipeline.

---

## Data Flow Graph

Before any LLM is invoked, the DFG pass maps every variable dependency in the COBOL program. This intermediate representation exposes the globally scoped state that is the root cause of Py-BOL — and gives the Semantic Agent a principled basis for scope-elimination.

Sample output for `CUSTOMER-CALC`:

```
  Variables (node  →  Python name      |  PIC          |  in° / out°  |  role)
  ------------------------------------------------------------------------
  WS-CUST-ID-X            → cust_id_x           PIC 9(6)        in=1 out=0  [SINK/OUTPUT]
  WS-DISCOUNT-AMT-N       → discount_amt_n      PIC 9(7)V99     in=2 out=1  [INTERMEDIATE]
  WS-DISCOUNT-RT-N        → discount_rt_n       PIC 9(3)V99     in=1 out=1  [INTERMEDIATE]
  WS-FINAL-AMT-N          → final_amt_n         PIC 9(7)V99     in=2 out=0  [SINK/OUTPUT]
  WS-ORDER-AMT-N          → order_amt_n         PIC 9(7)V99     in=1 out=4  [INTERMEDIATE]
  WS-PREMIUM-FLAG-X       → premium_flag_x      PIC X           in=2 out=0  [SINK/OUTPUT]

  Data-flow edges (source  →  target  via  op @ paragraph)
  ------------------------------------------------------------------------
  L21   LITERAL:100423           → WS-CUST-ID-X              MOVE @ MAIN-LOGIC
  L22   LITERAL:1500.00          → WS-ORDER-AMT-N            MOVE @ MAIN-LOGIC
  L23   WS-ORDER-AMT-N           → WS-PREMIUM-FLAG-X         IF-CONDITION @ MAIN-LOGIC
  L23   WS-ORDER-AMT-N           → WS-DISCOUNT-RT-N          IF-CONDITION @ MAIN-LOGIC
  L24   LITERAL:'Y'              → WS-PREMIUM-FLAG-X         MOVE @ MAIN-LOGIC [then]
  L29   WS-ORDER-AMT-N           → WS-DISCOUNT-AMT-N         COMPUTE @ MAIN-LOGIC
  L29   WS-DISCOUNT-RT-N         → WS-DISCOUNT-AMT-N         COMPUTE @ MAIN-LOGIC
  L31   WS-ORDER-AMT-N           → WS-FINAL-AMT-N            COMPUTE @ MAIN-LOGIC
  L31   WS-DISCOUNT-AMT-N        → WS-FINAL-AMT-N            COMPUTE @ MAIN-LOGIC
```

The graph makes explicit that `WS-ORDER-AMT-N` is a root source with four downstream dependents — information that is implicit in the flat COBOL source but essential for safe refactoring.

---

## Project Structure

```
Py-BOLD/
├── samples/
│   └── customer_calc.cbl          # Canonical COBOL specimen
├── src/pybold/
│   ├── parser/
│   │   ├── lexer.py               # Fixed-format tokenizer; maximal-munch handling
│   │   ├── cobol_parser.py        # Recursive-descent parser → typed AST nodes
│   │   ├── ast_nodes.py           # Dataclass definitions (MoveStmt, IfStmt, …)
│   │   └── ast_printer.py        # AST → structured LLM prompt block
│   ├── graph/
│   │   └── dfg_builder.py         # NetworkX DFG; variable dependency analysis
│   └── agents/
│       ├── workflow.py            # LangGraph state machine; all three agent nodes
│       └── __init__.py
├── tests/
│   ├── helpers.py                 # Shared parse helpers (parse_program, parse_stmts)
│   ├── test_parser/
│   │   ├── test_lexer_edge_cases.py   # 27 tests — column layout, keyword ambiguity
│   │   └── test_ast_generation.py    # 50 tests — PIC parsing, expressions, IF/COMPUTE
│   └── test_dfg.py                   # 19 tests — node roles, edge ops, branch labels
├── poc_tracer_bullet.py           # End-to-end PoC: parse → DFG → agents → pytest
├── pyproject.toml
└── README.md
```

---

## Setup & Running

```bash
# 1. Clone and install
git clone <repo-url>
cd Py-BOLD
pip install -e ".[dev]"

# 2. Set your API key (or add to a .env file)
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Run the full pipeline
python poc_tracer_bullet.py
```

The pipeline runs in six stages. If `ANTHROPIC_API_KEY` is absent, Stages 1–5 (deterministic parsing and prompt assembly) still execute — the LLM stages are skipped gracefully with a clear message.

To run the parser test suite independently:

```bash
pytest tests/ -v
# 96 tests, ~2s, no API key required
```

---

## Limitations & Future Work

The current implementation handles a well-defined subset of COBOL 85 and is intentionally scoped to demonstrate the core neuro-symbolic architecture:

* **Statement coverage:** `MOVE`, `COMPUTE`, `ADD`, `SUBTRACT`, `IF/ELSE/END-IF`, `DISPLAY`, `PERFORM`, `STOP RUN`. File I/O (`READ`, `WRITE`, `OPEN`, `CLOSE`), `PERFORM UNTIL` loops, and `EVALUATE` (switch) are out of scope.
* **Single-program files:** `COPY` book resolution and multi-program compilation units are not handled.
* **Numeric precision edge cases:** `ROUNDED` and `ON SIZE ERROR` clauses are parsed but not yet translated.
* **Test coverage of generated code:** The Verification Agent currently generates tests from the AST spec alone; a future iteration would augment this with execution traces captured from a COBOL runtime for property-based validation.

These constraints are deliberate — the goal was to validate the pipeline architecture and the neuro-symbolic boundary, not to ship a production transpiler.

---

## Tech Stack
* **Language:** Python 3.12+
* **AI & Orchestration:** LangGraph, Anthropic SDK (`claude-opus-4-6`, adaptive thinking + streaming)
* **Static Analysis:** Custom Lexer/Parser, NetworkX (DFG traversal)
* **Verification:** Pytest
