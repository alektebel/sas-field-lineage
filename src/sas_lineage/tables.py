"""
Table inventory: what a program touches, what survives the session, and which
names it could not resolve.

A SAS dataset lives in a library. WORK is the session's scratch library and is
dropped when the session ends, so a table is **persistent** exactly when it is
written or read through a libref that is not WORK. The parser folds an explicit
``WORK.`` away, so after parsing the rule is simply: a two-level name is
persistent, a one-level name is WORK and transient.

That line is what makes a lineage graph auditable. A WORK table is an
implementation detail of one run; a persistent table is a contract with
whatever reads it next, which is why a persistent name the macro pass could not
resolve is an error rather than a cosmetic gap -- the graph is then asserting a
dependency on a table nobody can name.

This module is deliberately dependency-free (standard library only) so the
stdlib-only web server and the parser can both use it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

WORK = "work"

# ``data _null_;`` names the null dataset: it produces nothing, so it is a
# statement about control flow rather than a table in the inventory.
_NOT_A_TABLE = {"_null_"}


def _has_macro(text: str) -> bool:
    return "&" in text or "%" in text


def libref_of(table: str) -> Optional[str]:
    """The library a table name refers to, or ``None`` when it cannot be known.

    ``None`` means genuinely unknown, not WORK: a one-level name is WORK, but a
    name whose libref position still holds an unexpanded ``&`` could expand to
    any library at all, and saying WORK there would be a guess.
    """
    if not table:
        return None
    head, sep, _rest = table.partition(".")
    if not sep:
        return None if _has_macro(table) else WORK
    return None if _has_macro(head) else head.lower()


def member_of(table: str) -> str:
    """The dataset name without its libref."""
    head, sep, rest = table.partition(".")
    return rest if sep else head


def is_persistent(table: str) -> Optional[bool]:
    """True when the table outlives the session, ``None`` when unknowable.

    ``None`` is a distinct answer on purpose: an unresolved name must not be
    silently counted as either persistent or transient.
    """
    lib = libref_of(table)
    if lib is None:
        return None
    return lib != WORK


def is_unresolved(table: str) -> bool:
    """True when the name still carries an unexpanded macro reference."""
    return _has_macro(table)


# --------------------------------------------------------------------------- #
# Table-level graph
# --------------------------------------------------------------------------- #
def table_graph(program) -> Tuple[Set[str], List[Tuple[str, str]]]:
    """All table names in the program plus its ``(input, output)`` edges."""
    tables: Set[str] = set()
    edges: List[Tuple[str, str]] = []
    for ds in program.data_steps:
        outs = ds.output_tables or ([ds.output_table] if ds.output_table else [])
        tables.update(outs)
        for inp in ds.input_tables:
            tables.add(inp)
            for out in outs:
                edges.append((inp, out))
    for ps in program.proc_steps:
        tables.update(ps.input_tables)
        tables.update(ps.output_tables)
        for out in ps.output_tables:
            for inp in ps.input_tables:
                if inp != out:
                    edges.append((inp, out))
    return tables, edges


def stage_of(edges: List[Tuple[str, str]]) -> Dict[str, int]:
    """Pipeline stage per table: the longest path from a table nothing writes.

    Stage 0 is a golden source (no producer); each further stage is one
    derivation away. The longest path, not the shortest, so a table that is
    also reachable by a short-cut still sorts after everything that feeds it.
    """
    producers: Dict[str, Set[str]] = {}
    for src, dst in edges:
        producers.setdefault(dst, set()).add(src)
    nodes = {n for e in edges for n in e}
    col: Dict[str, int] = {}

    def longest(n: str, seen: Set[str]) -> int:
        if n in col:
            return col[n]
        if n in seen:          # a cycle contributes no further depth
            return 0
        seen = seen | {n}
        best = 0
        for pnode in producers.get(n, set()):
            best = max(best, 1 + longest(pnode, seen))
        col[n] = best
        return best

    for n in nodes:
        longest(n, set())
    return col


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #
@dataclass
class TableInfo:
    """One dataset as the program uses it."""
    name: str
    libref: Optional[str]
    member: str
    persistent: Optional[bool]
    unresolved: bool
    stage: int = 0
    written_by: List[str] = field(default_factory=list)   # step labels
    read_by: List[str] = field(default_factory=list)

    @property
    def is_written(self) -> bool:
        return bool(self.written_by)

    @property
    def is_read(self) -> bool:
        return bool(self.read_by)

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "libref": self.libref,
            "member": self.member,
            "persistent": self.persistent,
            "unresolved": self.unresolved,
            "stage": self.stage,
            "written_by": list(self.written_by),
            "read_by": list(self.read_by),
        }


def build_inventory(program) -> Dict[str, TableInfo]:
    """Every table the program touches, keyed by name, in stage order."""
    tables, edges = table_graph(program)
    stages = stage_of(edges)
    info: Dict[str, TableInfo] = {}

    def entry(name: str) -> Optional[TableInfo]:
        if name in _NOT_A_TABLE:
            return None
        if name not in info:
            info[name] = TableInfo(
                name=name,
                libref=libref_of(name),
                member=member_of(name),
                persistent=is_persistent(name),
                unresolved=is_unresolved(name),
                stage=stages.get(name, 0),
            )
        return info[name]

    def touch(name: str, label: str, written: bool) -> None:
        got = entry(name)
        if got is None:
            return
        (got.written_by if written else got.read_by).append(label)

    for idx, ds in enumerate(program.data_steps):
        label = f"DATA step #{idx + 1}"
        for out in (ds.output_tables or ([ds.output_table] if ds.output_table else [])):
            touch(out, label, True)
        for inp in ds.input_tables:
            touch(inp, label, False)
    for idx, ps in enumerate(program.proc_steps):
        label = f"PROC {ps.proc_name} #{idx + 1}"
        for out in ps.output_tables:
            touch(out, label, True)
        for inp in ps.input_tables:
            touch(inp, label, False)

    for name in tables:
        entry(name)
    return dict(sorted(info.items(), key=lambda kv: (kv[1].stage, kv[0])))


# --------------------------------------------------------------------------- #
# Diagnostics
# --------------------------------------------------------------------------- #
def diagnose(program) -> Dict[str, object]:
    """Report the persistent tables whose names could not be resolved.

    Only unresolved names are reported as errors. A persistent table that is
    read but never written, or written but never read, is a design observation
    about the pipeline, not a defect of the parse, so it is left out.

    Unresolved names split into two buckets because the confidence differs:

    * ``errors`` -- the libref resolved but the member did not (``bsgl.&tab``),
      so we know a persistent table is involved and we cannot name it.
    * ``unknown`` -- the libref itself is unresolved (``&lib..c20``, ``&out``),
      so the table may be persistent or may be WORK. Reporting these as
      persistent errors would be a guess; ignoring them would hide the gap.
    """
    inventory = build_inventory(program)
    report = getattr(program, "macro_report", {}) or {}

    runtime = set(report.get("runtime_symbols") or [])
    automatic = set(report.get("automatic_symbols") or [])
    cycles = set(report.get("symbol_cycles") or [])
    missing_macros = set(report.get("unresolved_macros") or [])

    def cause_of(ref: str) -> str:
        """Why one macro reference in a table name did not resolve.

        Naming the cause is the difference between a report that says a table
        is broken and one that says what to do about it: a run-time symput is
        a modelling limit, a missing macro is a file you forgot to include, and
        an unassigned name is usually a typo.
        """
        if ref in runtime:
            return "set at run time by call symput"
        if ref in automatic:
            return "SAS automatic variable, never static"
        if ref in cycles:
            return "%let dependency cycle"
        if ref in missing_macros:
            return "macro not found in this source"
        return "never assigned in this source"

    errors: List[Dict[str, object]] = []
    unknown: List[Dict[str, object]] = []
    for info in inventory.values():
        if not info.unresolved:
            continue
        refs = sorted(_macro_names(info.name))
        row = {
            "table": info.name,
            "libref": info.libref,
            "stage": info.stage,
            "written_by": list(info.written_by),
            "read_by": list(info.read_by),
            "macro_refs": refs,
            "causes": {ref: cause_of(ref) for ref in refs},
        }
        (errors if info.persistent else unknown).append(row)

    persistent = [i for i in inventory.values() if i.persistent]
    return {
        "errors": errors,
        "unknown": unknown,
        "counts": {
            "tables": len(inventory),
            "persistent": len(persistent),
            "transient": len([i for i in inventory.values() if i.persistent is False]),
            "unresolved": len(errors) + len(unknown),
        },
        "libraries": sorted({i.libref for i in persistent if i.libref}),
        "unresolved_symbols": list(report.get("unresolved_symbols") or []),
        "unresolved_macros": sorted(missing_macros),
        "automatic_symbols": sorted(automatic),
        "runtime_symbols": sorted(runtime),
        "symbol_cycles": sorted(cycles),
        "macro_cycles": list(report.get("macro_cycles") or []),
        "macro_expansion_ran": bool(report),
    }


_MACRO_REF_RE = re.compile(r"[&%]+([A-Za-z_]\w*)")


def _macro_names(table: str) -> Set[str]:
    """The ``&name`` / ``%name`` references left inside a table name."""
    return {m.group(1).lower() for m in _MACRO_REF_RE.finditer(table)}
