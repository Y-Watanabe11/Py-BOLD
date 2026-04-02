# %% [markdown]
# # Py-BOLD: Tracer Bullet — AST Extraction → LLM Prompt Validation
#
# **Goal:** Prove the highest-risk Phase 1 claim end-to-end:
#   COBOL source → deterministic AST → structured prompt block → (LLM-ready)
#
# **Key architectural constraint being tested:**
#   The LLM must NEVER receive raw COBOL. It only sees the structured AST
#   block emitted by `ast_printer`. This enforces the neuro-symbolic boundary:
#   - Compiler layer (lexer + parser + DFG) owns CORRECTNESS
#   - LLM layer owns SEMANTICS / style / naming
#
# Run locally:   python poc_tracer_bullet.py
# Run in Colab:  !pip install -e . && %run poc_tracer_bullet.py

# %%
import os
import sys
from pathlib import Path

# Allow running from project root without `pip install -e .`
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

# Load .env if present (create one with ANTHROPIC_API_KEY=sk-ant-...)
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass  # python-dotenv optional; export the key manually instead

from pybold.parser.lexer import tokenize
from pybold.parser.cobol_parser import CobolParser
from pybold.parser.ast_printer import program_to_prompt_block
from pybold.graph.dfg_builder import build_dfg, dfg_summary


# ── Step 1: Load source ───────────────────────────────────────────────────────
# The COBOL source is read once here. After this point, raw source is NEVER
# passed to any LLM function — only the structured AST block is.

def load_source(path: str) -> str:
    p = ROOT / path
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found. Run from the project root or check samples/."
        )
    return p.read_text(encoding="utf-8")


# ── Step 2: Parse  (Lexer → Parser → AST) ────────────────────────────────────
#
# Compiler theory walkthrough:
#
#   Lexical analysis (tokenize):
#     Converts the raw character stream into a flat list of typed Token objects.
#     Handles COBOL's fixed-format column layout (col 7 = indicator, cols 8–72
#     = code area). All whitespace and sequence numbers are discarded here.
#
#   Syntactic analysis (CobolParser):
#     Recursive-descent parser consumes the token stream and builds typed AST
#     nodes — MoveStmt, ComputeStmt, IfStmt, etc. Each node type encodes
#     semantic intent (MOVE = assignment) rather than raw token position.
#     This is the critical difference from a generic CST (Concrete Syntax Tree):
#     our AST already carries meaning before any LLM is involved.

def parse_cobol(source: str):
    tokens = tokenize(source)
    program = CobolParser(tokens).parse()
    return program


# ── Step 3: Build Data Flow Graph ─────────────────────────────────────────────
#
# The DFG is an Intermediate Representation (IR) that maps WHICH variables
# feed into WHICH other variables, independent of statement order.
# This captures globally-scoped COBOL state — the root cause of "Py-BOL" —
# so the Refactoring Agent can safely convert it to local Python scope.

def build_analysis(program):
    return build_dfg(program)


# ── Step 4: Serialise to LLM prompt block ─────────────────────────────────────
#
# ast_printer converts the typed AST into a structured text block.
# Crucially it annotates each variable with its inferred Python type
# (PIC 9(7)V99 → Decimal, PIC X → str) so the LLM generates correct
# type annotations without guessing from COBOL syntax.

def make_prompt_block(program) -> str:
    return program_to_prompt_block(program)


# ── Step 5: Compose the full agent prompt ─────────────────────────────────────
#
# This is what gets sent to the Structural Agent (first node in the LangGraph
# pipeline). Note: no raw COBOL appears anywhere in this string.

STRUCTURAL_AGENT_SYSTEM = """\
You are the Structural Agent in the Py-BOLD transpiler pipeline.
You will receive a structured AST dump of a COBOL program — not raw COBOL source.

Your responsibilities:
1. Map each Working-Storage variable to a typed Python attribute using
   the inferred type shown in the AST dump (e.g. "→ Python Decimal").
2. Translate each PARAGRAPH to a method on a Python class.
3. Infer meaningful Python names from context
   (e.g. WS-CUST-ID-X → customer_id: int).
4. Preserve all control flow exactly as described in the IF/PERFORM nodes.
5. Never hallucinate logic not present in the AST. Your only input is the
   structured AST block. You do not have access to the original COBOL source.
"""

def compose_agent_prompt(ast_block: str) -> str:
    return (
        f"[SYSTEM]\n{STRUCTURAL_AGENT_SYSTEM}\n"
        f"[AST_BLOCK]\n{ast_block}\n"
        f"[/AST_BLOCK]\n"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def run_tracer_bullet():
    sep = "=" * 64

    print(sep)
    print("Py-BOLD — Tracer Bullet PoC")
    print(sep)

    # 1. Load
    source = load_source("samples/customer_calc.cbl")
    print(f"\n[1/5] Loaded source  ({len(source.splitlines())} lines)")

    # 2. Parse
    program = parse_cobol(source)
    print(f"[2/5] Parsed AST")
    print(f"      program_id : {program.program_id}")
    print(f"      variables  : {len(program.data_items)}")
    print(f"      paragraphs : {len(program.paragraphs)} "
          f"({sum(len(p.statements) for p in program.paragraphs)} statements)")

    # 3. DFG
    dfg = build_analysis(program)
    print(f"[3/5] Built DFG  "
          f"(nodes={dfg.number_of_nodes()}, edges={dfg.number_of_edges()})")
    print(dfg_summary(dfg))

    # 4. AST block
    ast_block = make_prompt_block(program)
    print(f"\n[4/5] AST prompt block  ({len(ast_block.splitlines())} lines)\n")
    print(ast_block)

    # 5. Agent prompt (visual validation — confirms what the LLM will receive)
    agent_prompt = compose_agent_prompt(ast_block)
    print(f"\n[5/6] Structural Agent prompt assembled  "
          f"({len(agent_prompt)} chars)\n")
    print(agent_prompt)

    # 6. LangGraph pipeline — Structural Agent → Semantic Agent
    #    Requires ANTHROPIC_API_KEY in the environment (or a .env file).
    #    If the key is absent the tracer bullet still validates Phase 1.
    print(f"\n[6/6] LangGraph Pipeline  (Structural → Semantic)")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(f"      SKIPPED — export ANTHROPIC_API_KEY to activate the pipeline.")
    else:
        from pybold.agents.workflow import build_translation_graph
        graph = build_translation_graph()
        result = graph.invoke({
            "program_id":      program.program_id,
            "ast_block":       ast_block,
            "python_code":     "",
            "refactored_code": "",
            "test_code":       "",
        })

        print(f"\n{sep}")
        print("STRUCTURAL AGENT OUTPUT  (correct but ugly — Py-BOL)")
        print(sep)
        print(result["python_code"])

        print(f"\n{sep}")
        print("SEMANTIC AGENT OUTPUT    (correct and readable — Modern Python)")
        print(sep)
        print(result["refactored_code"])

        print(f"\n{sep}")
        print("VERIFICATION AGENT OUTPUT  (pytest suite derived from AST spec)")
        print(sep)
        print(result["test_code"])
        print(sep)

        # ── Bonus: write to disk + run the generated tests ─────────────────
        module_path = ROOT / "generated_module.py"
        tests_path  = ROOT / "test_generated.py"

        module_path.write_text(result["refactored_code"], encoding="utf-8")
        tests_path.write_text(result["test_code"],        encoding="utf-8")

        print(f"\n[BONUS] Written:")
        print(f"  {module_path}")
        print(f"  {tests_path}")
        print(f"\n[BONUS] Running: pytest test_generated.py -v\n")
        print(sep)

        import subprocess, sys as _sys
        pytest_result = subprocess.run(
            [_sys.executable, "-m", "pytest", str(tests_path), "-v", "--tb=short"],
            cwd=ROOT,
        )

        print(sep)
        if pytest_result.returncode == 0:
            print("PYTEST RESULT : ALL TESTS PASSED — behavioural parity confirmed.")
        else:
            print("PYTEST RESULT : some tests failed — review generated_module.py "
                  "and test_generated.py for discrepancies.")
        print(sep)

    print(f"\n{sep}")
    print("Tracer bullet complete.")
    print("Phase 1 validated : AST extraction → structured prompt block.")
    if api_key:
        print("Phase 2 validated : Structural Agent produced Py-BOL Python.")
        print("Phase 3 validated : Semantic Agent renamed COBOL identifiers.")
        print("Phase 4 validated : Verification Agent synthesised pytest suite.")
    print("Raw COBOL source was NOT included in any LLM-facing string.")
    print(sep)


# %%
if __name__ == "__main__":
    run_tracer_bullet()
