# I Built an AI That Modernizes Legacy COBOL — And Then Made It Prove Its Own Work

## What happens when you let a language model touch 800 billion lines of business-critical code

---

Look at this variable name:

```
WS-CUST-ID-X
```

Take a guess. Customer something. ID, obviously. The `X` at the end — no idea.

Now look at it after a standard AI migration tool has "modernized" it:

```python
ws_cust_id_x: int = 0
```

Same name. Snake-cased. Still completely opaque. This is what the industry calls **Py-BOL** — Python code that runs in a modern environment but thinks in COBOL. It compiles. It executes. It is practically unmaintainable.

I built a system to fix this. And then I made it write its own tests.

---

## The $3 Trillion Problem No One Talks About

COBOL — Common Business-Oriented Language — was designed in 1959. It currently processes an estimated **$3 trillion in financial transactions every day**. Roughly 95% of ATM transactions and 80% of in-person credit card swipes run on COBOL. The US federal government runs core tax processing on it. Most major banks do too.

The engineers who wrote these systems are retiring. The systems themselves are not.

There have been attempts to migrate. Most of them produce Py-BOL. You feed COBOL into a transpiler, out comes Python, and at first glance it looks fine. Functions, classes, indentation. But look closer:

```python
@dataclass
class CustomerCalc:
    ws_cust_id_x: int = 0
    ws_order_amt_n: Decimal = Decimal("0")
    ws_discount_rt_n: Decimal = Decimal("0")
    ws_discount_amt_n: Decimal = Decimal("0")
    ws_final_amt_n: Decimal = Decimal("0")
    ws_premium_flag_x: str = 'N'
```

Every variable name is a COBOL artifact. `WS-` is the Working-Storage prefix — it means "this is a global state variable." `-N` means numeric. `-X` means alphanumeric. `-RT-` means rate. None of this is Python. None of this is readable to a developer who didn't write the original COBOL in 1987.

The business logic survived the migration intact. The business *intent* did not.

---

## Why Zero-Shot LLMs Make It Worse

The obvious solution is to ask a modern LLM: "Here's my COBOL. Give me clean Python."

The problem is hallucination — and not in the obvious way.

The model doesn't fabricate code out of nowhere. It does something subtler: it *guesses* at the business logic from the variable names and control flow, and it guesses wrong often enough that you can't trust the output. A `COMPUTE` statement that calculates a discount rate might be re-expressed as a slightly different formula. An `IF` branch condition might be off by one comparison operator. The code looks idiomatic, it reads cleanly — and it silently produces wrong answers for edge cases that the original system handled correctly for thirty years.

Even when the logic is preserved, you have no way to verify it. There's no ground truth. The COBOL is the spec, and you just threw it away.

I spent about two weeks going down this path before I stopped and asked a different question: **what if I didn't let the LLM touch the logic at all?**

---

## The Neuro-Symbolic Insight

The core problem with zero-shot translation is that you're asking one system to do two fundamentally different jobs simultaneously:

1. **Preserve correctness** — every branch, every arithmetic expression, every edge case in the original must survive
2. **Restore intent** — `ws_order_amt_n` should become `order_amount`, `ws_premium_flag_x` should become `is_premium`

These jobs require different tools. Correctness is a matter of formal structure — it's deterministic, verifiable, not a job for a probabilistic model. Intent is semantic — it requires understanding business domain vocabulary, which is exactly what LLMs are good at.

So I separated them.

**Compiler theory handles correctness. The LLM handles meaning.**

The system I built — Py-BOLD — enforces this at the data layer. Raw COBOL source never reaches any LLM. The only thing that crosses the neuro-symbolic boundary is a structured AST block emitted by a deterministic parser. The LLM cannot hallucinate logic that isn't in the AST because the AST is all it can see.

Here is the full pipeline:

```
┌─────────────────────────────────────────────────────────────────┐
│                        COBOL Source                             │
│              (never crosses the boundary below)                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              DETERMINISTIC COMPILER LAYER                       │
│                                                                 │
│   Lexer ──► Recursive-Descent Parser ──► Typed AST Nodes       │
│                                   │                            │
│                                   └──► Data Flow Graph (DFG)   │
│                                                                 │
│   Owns: CORRECTNESS  ·  Verifiable  ·  No LLM involved         │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                   AST Block only
              ══════════════╪══════════════
                 NEURO-SYMBOLIC BOUNDARY
              ══════════════╪══════════════
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  LangGraph AGENT PIPELINE                       │
│                                                                 │
│  ┌──────────────────┐      ┌──────────────────┐                │
│  │ Structural Agent │ ───► │  Semantic Agent  │                │
│  │                  │      │                  │                │
│  │ AST → Py-BOL     │      │ Py-BOL → Python  │                │
│  │ (ugly, correct)  │      │ (readable, same  │                │
│  │                  │      │  logic)          │                │
│  └──────────────────┘      └────────┬─────────┘               │
│                                     │                          │
│                                     ▼                          │
│                      ┌──────────────────────────┐              │
│                      │   Verification Agent     │              │
│                      │                          │              │
│                      │ AST spec + refactored    │              │
│                      │ code → pytest suite      │              │
│                      │                          │              │
│                      │  ✓ 5 passed in 0.12s    │              │
│                      └──────────────────────────┘              │
│                                                                 │
│   Owns: SEMANTICS  ·  Style  ·  Naming  ·  Verification        │
└─────────────────────────────────────────────────────────────────┘
```

The diagram shows the key property: the AST block is the only artifact that crosses the boundary. Everything above the line is deterministic and auditable. Everything below it is probabilistic but strictly constrained by the AST spec — the LLM cannot invent what the AST does not contain.

---

## Building the Anchor: The Deterministic Parser

Before any AI is invoked, Py-BOLD runs a custom lexer and recursive-descent parser over the COBOL source. The output is a typed Abstract Syntax Tree — not a generic parse tree, but one where every node encodes semantic intent.

A `MoveStmt` node means assignment. A `ComputeStmt` means expression evaluation. An `IfStmt` carries both branches as typed child nodes. The parser doesn't just know *what tokens are present* — it knows *what they mean*.

This matters because COBOL has a famous tokenization ambiguity that caught me early: the **maximal-munch problem**.

In COBOL, integers between 1 and 49 (plus 66, 77, and 88) are valid level numbers for variable declarations. They also appear as numeric literals in `COMPUTE` statements. A context-free lexer can't tell the difference — `15` in `PIC 9(15)` and `15` in `COMPUTE X = 15` tokenize identically.

My lexer always emits `TT.LEVEL` for these values (the conservative choice), and the parser recovers the correct semantics in context — stripping zero-padding from PIC strings, converting LEVEL tokens back to numeric literals in expression position. This is the kind of implementation detail that only surfaces when you actually build a parser instead of wrapping an existing one. It took me the better part of a day to diagnose, and I now have four named regression tests for it.

After parsing, the system builds a **Data Flow Graph** using NetworkX — a directed graph where nodes are variables and edges represent data dependencies, annotated with the operation that created them, the paragraph they appear in, and whether they occur inside a `then` or `else` branch.

```
L23   WS-ORDER-AMT-N  →  WS-PREMIUM-FLAG-X    IF-CONDITION @ MAIN-LOGIC
L23   WS-ORDER-AMT-N  →  WS-DISCOUNT-RT-N     IF-CONDITION @ MAIN-LOGIC
L29   WS-ORDER-AMT-N  →  WS-DISCOUNT-AMT-N    COMPUTE @ MAIN-LOGIC
L31   WS-DISCOUNT-AMT-N  →  WS-FINAL-AMT-N    COMPUTE @ MAIN-LOGIC
```

This makes explicit that `WS-ORDER-AMT-N` is a root source with four downstream dependents — information that is completely implicit in the flat COBOL source but essential for safe scope elimination. The globally scoped state that defines Py-BOL is now a first-class data structure.

---

## The Agent Pipeline

With the AST as the anchor, I built a three-node LangGraph pipeline using the Anthropic SDK directly — no LangChain wrapper.

**Why no LangChain?** Early versions used it. The wrapper made adaptive thinking inaccessible and the abstraction layer obscured what was actually being sent to the model. I needed to know exactly what the LLM received. Direct SDK access also gave me streaming with no HTTP timeout risk on long outputs — essential when `max_tokens` is set high enough for complex programs.

### Node 1: The Structural Agent

The Structural Agent receives the AST block and one instruction: translate mechanically, rename nothing.

Its output is Py-BOL. That's intentional. `ws_order_amt_n` stays `ws_order_amt_n`. The class is named `CustomerCalc`, not `CustomerDiscountCalculator`. Every COBOL construct maps 1:1 to its Python equivalent:

- `MOVE x TO y` → `self.y = self.x`
- `COMPUTE x = expr` → `self.x = expr`
- `IF cond ... ELSE ... END-IF` → standard `if/else`
- `PIC 9(7)V99` → `Decimal` field

The output is ugly. It's also **verifiable** — every line can be checked against the AST mechanically, without running the code. Correctness is auditable.

### Node 2: The Semantic Agent

The Semantic Agent never sees the COBOL. It sees the Structural Agent's Python output and one task: rename everything to reveal business intent.

This is the key architectural insight about **bounded error surface**. By isolating semantic refactoring into a Python-to-Python pipeline, the LLM's hallucination surface is strictly constrained. It cannot invent new logic — there is no COBOL to misread. As long as the Semantic Agent is restricted to renaming and structure-preserving refactoring (which the system prompt enforces), logic-changing errors are prevented by design: any naming inconsistency it introduces surfaces immediately as a `NameError` or `AttributeError` at runtime rather than a silent wrong answer buried in arithmetic. The architecture does not make errors impossible; it makes the category of errors that actually matter — silent logic corruption — structurally detectable.

```
# ── Structural Agent output (correct, but COBOL names intact) ──
ws_cust_id_x:     int     = 0              # ← WS- prefix, -X suffix
ws_order_amt_n:   Decimal = Decimal("0")   # ← WS- prefix, -N suffix
ws_premium_flag_x: str    = 'N'            # ← WS- prefix, -FLAG-X suffix

# ── Semantic Agent output (same logic, human intent restored) ──
customer_id:   int     = 0              # ✓ WS-CUST-ID-X decoded
order_amount:  Decimal = Decimal("0")   # ✓ WS-ORDER-AMT-N decoded
is_premium:    str     = 'N'            # ✓ WS-PREMIUM-FLAG-X decoded
```

The COBOL naming conventions decode predictably: `WS-` prefix strips. `-N` suffix indicates Decimal. `-FLAG-X` suffix becomes `is_<concept>`. `WS-ORDER-AMT-N` → `order_amount`. The Semantic Agent doesn't guess — it decodes.

### Node 3: The Verification Agent

This is the part that surprised me most when I built it.

Modernization without verification is just liability transfer. You've taken a system that worked — provably, for decades — and replaced it with something that looks cleaner but might not behave identically. The only way to prove behavioral parity is a test suite that covers every execution path in the original.

Writing those tests manually defeats the purpose of automation. But the AST already contains everything needed to derive them: initial variable values, branch conditions, COMPUTE expressions, DISPLAY outputs.

The Verification Agent takes the AST block (the behavioral ground truth) and the refactored Python (for class and method names) and generates a pytest module:

```python
def test_main_logic_premium_branch(program):
    program.main_logic()
    assert program.order_amount == Decimal("1500.00"),   "order_amount should be 1500.00"
    assert program.is_premium == 'Y',                   "is_premium should be Y for order > 1000"
    assert program.discount_amount == Decimal("225.00"), "discount_amount should be 15% of 1500"
    assert program.final_amount == Decimal("1275.00"),   "final_amount should be 1500 - 225"
```

The agent also detected something I hadn't fully thought through: the COBOL program hardcodes `MOVE 1500.00 TO WS-ORDER-AMT-N` at the top of `MAIN-LOGIC`, making the else-branch unreachable through normal execution. Rather than generating a broken test, it adapted — testing the branching arithmetic directly by setting fields as the COBOL interpreter would have them. It understood the program's reachability constraints from the AST spec.

The final output:

```
collected 5 items

test_generated.py::test_initial_values              PASSED  ✓
test_generated.py::test_main_logic_premium_branch   PASSED  ✓
test_generated.py::test_main_logic_standard_branch  PASSED  ✓
test_generated.py::test_main_logic_display_output   PASSED  ✓
test_generated.py::test_full_run                    PASSED  ✓

============ 5 passed in 0.12s ============
```

---

## How Well Does It Actually Work?

This is a proof of concept, so I want to be honest about the evaluation rather than oversell it.

**What I tested:** One COBOL program — `CUSTOMER-CALC` — covering the core statement types: `MOVE`, `COMPUTE`, `IF/ELSE/END-IF`, `DISPLAY`, and `STOP RUN`. Six working-storage variables, one paragraph, one conditional branch.

**Structural translation:** Zero manual fixes required on the canonical sample. Every COBOL construct mapped to its Python equivalent without intervention. The Structural Agent's output was directly runnable, and all five generated tests passed against it without modification.

**Semantic renaming:** The Semantic Agent decoded all six COBOL variable names correctly on the first pass:

| COBOL name | Structural Agent | Semantic Agent |
|---|---|---|
| `WS-CUST-ID-X` | `ws_cust_id_x` | `customer_id` |
| `WS-ORDER-AMT-N` | `ws_order_amt_n` | `order_amount` |
| `WS-DISCOUNT-RT-N` | `ws_discount_rt_n` | `discount_rate` |
| `WS-DISCOUNT-AMT-N` | `ws_discount_amt_n` | `discount_amount` |
| `WS-FINAL-AMT-N` | `ws_final_amt_n` | `final_amount` |
| `WS-PREMIUM-FLAG-X` | `ws_premium_flag_x` | `is_premium` |

The class name also upgraded correctly: `CustomerCalc` → `CustomerDiscountCalculator`.

**Comparison against zero-shot baseline:** I ran the same COBOL directly through `claude-opus-4-6` with a simple "translate this to Python" prompt. The model produced code that ran correctly and used reasonable variable names — but it also added a `logging` import that wasn't in the original, restructured the discount calculation into a helper method that didn't exist in the COBOL, and used `float` instead of `Decimal` for monetary values. None of these would have been caught without manual review. With Py-BOLD's pipeline, there was nothing to review: the AST is the spec, and the verification suite confirmed conformance automatically.

**Honest limitations:** A single sample is not a benchmark. The real test of the architecture would be a corpus of COBOL programs spanning multiple paragraphs, `PERFORM UNTIL` loops, and file I/O — none of which the current parser handles. What the sample does validate is the architectural claim: when the LLM is given a structured spec instead of raw source, its outputs become verifiable.

---

## The Lesson About Determinism

Early in the project I used `temperature=0.1` to push the model toward deterministic outputs. It helped — until I realized what I was actually doing.

**Low temperature doesn't just reduce variance. It reduces reasoning.** The model becomes less likely to explore alternative interpretations of ambiguous constructs, which means it also becomes less likely to *notice* that a construct is ambiguous in the first place. You trade variance for a kind of confident shallowness.

I switched to the Anthropic SDK's adaptive thinking mode. The model privately commits to a reasoning path before producing output — it works through edge cases in its scratchpad, then writes the code. The result is higher logical determinism than temperature manipulation achieves, without the reasoning suppression. The thinking blocks are invisible in the terminal output, but you can feel their effect in the quality of the code: fewer silent errors, more consistent handling of COBOL constructs that don't have clean Python equivalents.

---

## What This Is Really About

Py-BOLD is a proof of concept, not a production tool. It handles a well-defined subset of COBOL 85 — `MOVE`, `COMPUTE`, `IF/ELSE`, `DISPLAY`, `PERFORM`. File I/O, `PERFORM UNTIL` loops, and multi-program compilation units are out of scope.

But the architecture is the point. **The highest value of generative AI in software engineering is not writing code from scratch. It is acting as a specialized worker within a heavily constrained, traditionally engineered pipeline.**

The Structural Agent can't hallucinate logic because all it sees is a structured AST. The Semantic Agent can't silently corrupt business rules because it only does Python-to-Python renaming. The Verification Agent can't write tests for behavior that isn't in the spec because the AST is the spec.

Every constraint is intentional. Every boundary exists because crossing it would introduce a category of error that the system cannot detect. The AI is powerful precisely because of what it's not allowed to do.

That's the lesson from two weeks of fighting COBOL: the future of AI-assisted engineering isn't less structure. It's more.

---

*The full source — parser, agents, and test suite — is available at [github.com/Y-Watanabe11/Py-BOLD](https://github.com/Y-Watanabe11/Py-BOLD).*
