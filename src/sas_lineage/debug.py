"""
Stage-by-stage trace of the parse, for finding *where* a name goes wrong.

The pipeline has four stages and a bug in any of them shows up as the same
symptom -- a table with the wrong name -- so guessing which stage is at fault
wastes most of the debugging time. This module prints each stage separately so
the question becomes "which stage first shows the wrong value":

  1. SYMBOLS   what %let / call symput resolved to, and in what order
  2. EXPANSION the lines the macro pass rewrote, source -> expanded
  3. STATEMENTS the statement stream the parser actually sees
  4. TABLES    the names the parser pulled out of those statements

Then a fifth section, SUSPECT, which is the one worth reading first: names the
parser reports as if they were real but that were built from a macro reference
it could not resolve. It finds them by parsing twice -- once normally and once
with unresolved references preserved -- and comparing. A name that differs
between the two runs was macro-built; if the preserved run still shows a ``&``,
the normal run's name is a fabrication, not a table.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Tuple

from .parser.preprocessor import MacroPreprocessor, expand_for_report, preprocess
from .parser.sas_parser import SASParser

_MACRO_REF_RE = re.compile(r"[&%]+([A-Za-z_]\w*)")


def _tables_of(program) -> List[Tuple[str, str, List[str]]]:
    """``(kind, output, inputs)`` for every step, in source order."""
    rows: List[Tuple[str, str, List[str]]] = []
    for ds in program.data_steps:
        rows.append(("DATA", ds.output_table, list(ds.input_tables)))
    for ps in program.proc_steps:
        rows.append((f"PROC {ps.proc_name}",
                     ps.output_table or "", [ps.input_table] if ps.input_table else []))
    return rows


def symbol_table(code: str) -> Dict[str, str]:
    """Every macro variable the pre-pass resolved, and to what."""
    pre = MacroPreprocessor(preserve_unknown=True)
    try:
        pre.preprocess(code)
    except Exception:
        pass
    return dict(sorted(pre.symbols.items()))


def macro_table(code: str) -> List[str]:
    """Names of the %macro definitions the pre-pass registered."""
    pre = MacroPreprocessor(preserve_unknown=True)
    try:
        pre.preprocess(code)
    except Exception:
        pass
    return sorted(pre.macros)


def unresolved_refs(code: str) -> List[str]:
    """Macro names still unresolved after expansion, deduplicated."""
    kept = expand_for_report(code)
    return sorted({m.group(1).lower() for m in _MACRO_REF_RE.finditer(kept)})


def suspect_tables(code: str) -> List[Dict[str, Any]]:
    """Table names the parser reports that were built from unresolved macros.

    Parsed twice: normally (an unknown ``&x`` collapses to nothing) and with
    references preserved. Where the two disagree, the name came from a macro;
    where the preserved side still holds a ``&``, the normal side is a name the
    parser invented out of the leftovers -- ``data &nope..C20;`` becomes the
    perfectly plausible table ``C20``, which is worse than an obvious error
    because nothing downstream can tell it from a real one.
    """
    normal = _tables_of(SASParser().parse(code, expand_macros=True))
    kept = _tables_of(SASParser().parse(expand_for_report(code)))
    out: List[Dict[str, Any]] = []
    for idx, (kind, got, got_in) in enumerate(normal):
        if idx >= len(kept):
            break
        _kind2, truth, truth_in = kept[idx]
        for role, a, b in (("output", got, truth),
                           *[("input", g, t) for g, t in zip(got_in, truth_in)]):
            if a == b or not b:
                continue
            if "&" in b or "%" in b:
                out.append({"step": kind, "role": role,
                            "reported": a, "unresolved_form": b,
                            "missing": sorted({m.group(1).lower()
                                               for m in _MACRO_REF_RE.finditer(b)})})
    return out


def expansion_diff(code: str, context: int = 0) -> List[str]:
    """Unified diff of the source before and after macro expansion."""
    before = code.splitlines()
    after = preprocess(code).splitlines()
    return list(difflib.unified_diff(before, after, "source", "expanded",
                                     n=context, lineterm=""))


def trace(code: str, show_statements: bool = False, max_rows: int = 60) -> str:
    """Render the full stage-by-stage trace."""
    lines: List[str] = []

    def section(title: str) -> None:
        lines.append("")
        lines.append(f"== {title} " + "=" * max(0, 68 - len(title)))

    section("1. SYMBOLS (what %let / call symput resolved to)")
    symbols = symbol_table(code)
    if not symbols:
        lines.append("  (none)")
    for name, value in symbols.items():
        flag = "  <- still unresolved" if _MACRO_REF_RE.search(value) else ""
        lines.append(f"  &{name:<24} = {value!r}{flag}")
    missing = unresolved_refs(code)
    if missing:
        lines.append(f"  NEVER RESOLVED: {', '.join(missing)}")
    macros = macro_table(code)
    lines.append(f"  %macro registered: {', '.join(macros) if macros else '(none)'}")

    section("2. EXPANSION (only the lines the macro pass rewrote)")
    diff = expansion_diff(code)
    if not diff:
        lines.append("  (macro pass changed nothing)")
    for row in diff[:max_rows]:
        lines.append(f"  {row}")
    if len(diff) > max_rows:
        lines.append(f"  ... {len(diff) - max_rows} more diff lines")

    if show_statements:
        section("3. STATEMENTS (what the parser sees, after expansion)")
        for text, line in SASParser()._tokenize(preprocess(code))[:max_rows]:
            lines.append(f"  {line:>5}: {text[:100]}")

    section("4. TABLES (what the parser pulled out)")
    program = SASParser().parse(code, expand_macros=True)
    rows = _tables_of(program)
    if not rows:
        lines.append("  (no steps found)")
    for kind, out, ins in rows[:max_rows]:
        lines.append(f"  {kind:<14} {out or '(none)':<28} <- {', '.join(ins) or '(none)'}")

    section("5. SUSPECT (names invented from an unresolved macro)")
    suspects = suspect_tables(code)
    if not suspects:
        lines.append("  (none - every reported name came out of the source or a "
                     "resolved macro)")
    for s in suspects:
        lines.append(f"  {s['step']} {s['role']}: reported {s['reported']!r} "
                     f"but the real name is {s['unresolved_form']!r} "
                     f"(missing: {', '.join(s['missing'])})")

    warnings = program.get_warnings() if hasattr(program, "get_warnings") else []
    if warnings:
        section("6. PARSER WARNINGS")
        for w in warnings[:max_rows]:
            lines.append(f"  [{w['kind']}] line {w.get('line')}: {w['message'][:110]}")

    return "\n".join(lines).lstrip("\n")
