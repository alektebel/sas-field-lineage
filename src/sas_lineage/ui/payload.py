"""
Build the explorer payload from a parsed SASProgram.

The result is shaped exactly like the mockup's inline model so the frontend
(Lineage Explorer) can render any real SAS program with the same interaction
model: layered datasets (nodes), data-flow (edges), per-field multi-hop traces,
golden inputs and per-hop value runs.

The mapping is intentionally convention-free and works from the parser's own
AST: tables flow through DATA/PROC steps, golden sources are the tables nothing
writes, and every assigned field gets a trace from its golden inputs.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ..ast.field_ast import FieldNode, SASProgram

# Palette copied verbatim from the mockup so the backend never has to guess.
COLORS = {
    "orange": "#d04a02",
    "amber": "#ffb600",
    "tang": "#eb8c00",
    "rose": "#e0301e",
    "ink": "#2d2d2d",
    "grey": "#8a8480",
    "line": "#dcd8d4",
}

# Layer taxonomy for the 0-4 register model. Columns beyond 4 fall back to a
# numbered layer so arbitrary pipelines still render.
_LAYER_TEMPLATE = [
    {"label": "Golden sources", "kicker": "Systems of record"},
    {"label": "Landing", "kicker": "Raw ingestion"},
    {"label": "Curated", "kicker": "Standardised registers"},
    {"label": "Marts", "kicker": "Integrated"},
    {"label": "Reporting", "kicker": "Consumption"},
]

_REGISTER_BY_COL = [
    "Golden Source",
    "Landing Zone",
    "Curated Register",
    "Integrated Marts",
    "Reporting Register",
]


class ProgramIndex:
    """Index a SASProgram for fast provenance / trace resolution."""

    def __init__(self, program: SASProgram):
        self.program = program
        # name -> list[(table, FieldNode, step_idx)]
        self.defs_by_name: Dict[str, List[Tuple[str, FieldNode, int]]] = {}
        # ordered unique field entries -> {id, name, table, step_idx, node}
        self.field_entries: List[Dict[str, Any]] = []
        self._build()

    def _build(self) -> None:
        seen = set()
        for step_idx, ds in enumerate(self.program.data_steps):
            for fn in ds.fields:
                entry = (ds.output_table, fn, step_idx)
                self.defs_by_name.setdefault(fn.name, []).append(entry)
                fid = self._field_id(ds.output_table, fn.name)
                if fid not in seen:
                    seen.add(fid)
                    self.field_entries.append({
                        "id": fid, "name": fn.name,
                        "table": ds.output_table, "step_idx": step_idx, "node": fn,
                    })

    @staticmethod
    def _field_id(table: Optional[str], name: str) -> str:
        return f"{table}.{name}" if table else name

    def resolve_field(self, field_id: str) -> Optional[Dict[str, Any]]:
        for e in self.field_entries:
            if e["id"] == field_id:
                return e
        return None

    def resolve_dep(
        self,
        dep_name: str,
        dep_table: Optional[str],
        step_idx: int,
        step_inputs: List[str],
    ) -> Optional[Tuple[str, FieldNode, int]]:
        """Resolve a dependency reference to a concrete defined field.

        Uses the same rules the mockup implies: pick the most recent definition
        of the name that this step could actually read (one of its inputs).
        """
        cands = self.defs_by_name.get(dep_name, [])
        earlier = [c for c in cands if c[2] < step_idx]
        for c in earlier:
            if c[0] in step_inputs:
                return c
        if earlier:
            return earlier[-1]
        # A definition on the same step (e.g. revenue before discount_amount).
        same = [c for c in cands if c[2] == step_idx]
        return same[-1] if same else None


# --------------------------------------------------------------------------- #
# Data-flow graph (nodes + edges + layers)
# --------------------------------------------------------------------------- #
def _all_tables(program: SASProgram) -> Tuple[Set[str], List[Tuple[str, str]]]:
    tables: Set[str] = set()
    edges: List[Tuple[str, str]] = []
    for ds in program.data_steps:
        out = ds.output_table
        tables.add(out)
        for inp in ds.input_tables:
            tables.add(inp)
            edges.append((inp, out))
    for ps in program.proc_steps:
        if ps.input_table:
            tables.add(ps.input_table)
        if ps.output_table:
            tables.add(ps.output_table)
            if ps.input_table:
                edges.append((ps.input_table, ps.output_table))
    return tables, edges


def _layer_cols(edges: List[Tuple[str, str]]) -> Dict[str, int]:
    """Assign each table a layer column (longest path from a source)."""
    producers: Dict[str, Set[str]] = {}
    for src, dst in edges:
        producers.setdefault(dst, set()).add(src)
    nodes = {n for e in edges for n in e}
    col: Dict[str, int] = {}

    def longest(n: str, seen: Set[str]) -> int:
        if n in col:
            return col[n]
        if n in seen:
            return 0
        seen = seen | {n}
        ins = producers.get(n, set())
        best = 0
        for p in ins:
            best = max(best, 1 + longest(p, seen))
        col[n] = best
        return best

    for n in nodes:
        longest(n, set())
    return col


def _node_field_counts(program: SASProgram) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for ds in program.data_steps:
        counts[ds.output_table] = max(counts.get(ds.output_table, 0), len(ds.fields))
    return counts


def build_nodes_edges(program: SASProgram) -> Dict[str, Any]:
    tables, edges = _all_tables(program)
    cols = _layer_cols(edges)
    max_col = max(cols.values(), default=0)
    field_counts = _node_field_counts(program)

    # Golden = a table that is never a data/proc output.
    outputs = {dst for _, dst in edges}
    producers = {src for src, _ in edges}

    # Rows: index within each column block.
    by_col: Dict[int, List[str]] = {}
    for t in tables:
        by_col.setdefault(cols.get(t, 0), []).append(t)
    row_of: Dict[str, int] = {}
    for c in sorted(by_col):
        for i, t in enumerate(sorted(by_col[c])):
            row_of[t] = i

    layer_meta = []
    for c in range(max_col + 1):
        if c < len(_LAYER_TEMPLATE):
            layer_meta.append({"id": f"l{c}", "col": c, **_LAYER_TEMPLATE[c]})
        else:
            layer_meta.append({
                "id": f"l{c}", "col": c,
                "label": f"Layer {c + 1}", "kicker": "Transform stage",
            })

    nodes = []
    for t in sorted(tables):
        c = cols.get(t, 0)
        golden = t not in outputs
        # Only tables that are read as inputs are golden; a pure sink is a leaf.
        system = "Golden source" if golden else ("SAS pipeline · staged" if c == 0 else "SAS job")
        register = _REGISTER_BY_COL[c] if c < len(_REGISTER_BY_COL) else f"Register {c + 1}"
        nodes.append({
            "id": t,
            "name": t.upper(),
            "system": system,
            "col": c,
            "row": row_of[t],
            "register": register,
            "layer": layer_meta[c]["label"],
            "golden": golden,
            "steward": "Golden source owner" if golden else "Pipeline owner",
            "refresh": "Near real time" if golden else "Batch run",
            "fieldCount": field_counts.get(t, 0),
        })

    return {
        "N": nodes,
        "E": [[a, b] for a, b in edges],
        "LAYERS": layer_meta,
        "maxCol": max_col,
    }


# --------------------------------------------------------------------------- #
# Field traces (golden source -> terminal field) and golden inputs
# --------------------------------------------------------------------------- #
def _walk_chain(
    index: ProgramIndex,
    entry: Dict[str, Any],
    inputs_set: Set[Tuple[str, Optional[str]]],
) -> List[Tuple[str, FieldNode, int]]:
    """Return the defined-field hops feeding this field, leaves-first."""
    seen: Set[Tuple[str, str, int]] = set()      # entry guard — breaks cycles
    recorded = set()                              # dedupe output by (table, name)
    chain: List[Tuple[str, FieldNode, int]] = []

    def record(table: str, fn: FieldNode, idx: int) -> None:
        key = (table, fn.name)
        if key in recorded:
            return
        recorded.add(key)
        chain.append((table, fn, idx))

    def visit(table: str, fn: FieldNode, idx: int) -> None:
        guard = (table, fn.name, idx)
        if guard in seen:
            return
        seen.add(guard)
        ds = index.program.data_steps[idx]
        step_inputs = ds.input_tables
        for dep in fn.dependencies:
            resolved = index.resolve_dep(dep.name, dep.table, idx, step_inputs)
            if resolved is not None:
                visit(resolved[0], resolved[1], resolved[2])
            else:
                inputs_set.add((dep.name, dep.table or (step_inputs[0] if step_inputs else None)))
        record(table, fn, idx)

    ds = index.program.data_steps[entry["step_idx"]]
    for dep in entry["node"].dependencies:
        resolved = index.resolve_dep(dep.name, dep.table, entry["step_idx"], ds.input_tables)
        if resolved is not None:
            visit(resolved[0], resolved[1], resolved[2])
        else:
            inputs_set.add((dep.name, dep.table or (ds.input_tables[0] if ds.input_tables else None)))
    record(entry["table"], entry["node"], entry["step_idx"])
    return chain


def _golden_table_for(input_set, index: ProgramIndex) -> List[str]:
    """Ordered list of contributing golden source table names."""
    outs = {dst for _, dst in _all_tables(index.program)[1]}
    golden_sources = []
    gold_names = set()
    for name, table in input_set:
        if table and table not in outs and table not in gold_names:
            gold_names.add(table)
            golden_sources.append(table.upper())
    return golden_sources or ["Golden source"]


def build_fields(program: SASProgram, index: ProgramIndex) -> List[Dict[str, Any]]:
    fields = []
    for entry in index.field_entries:
        inputs_set: Set[Tuple[str, Optional[str]]] = set()
        try:
            chain = _walk_chain(index, entry, inputs_set)
        except Exception:
            # Never let one bad trace break the whole explorer.
            chain = [(entry["table"], entry["node"], entry["step_idx"])]

        golden = _golden_table_for(inputs_set, index)

        # Steps: numbered hops, terminal field last.
        steps = []
        for i, (table, fn, _idx) in enumerate(chain):
            is_last = i == len(chain) - 1
            fm = _describe_transform(fn)
            steps.append({
                "node": table,
                "field": fn.name,
                "transform": fm,
                "job": _job_for(table, is_last),
                "merge": [],
            })

        inputs = []
        for name, table in sorted(inputs_set, key=lambda x: (x[0] or "", x[1] or "")):
            inputs.append({
                "key": f"{table}.{name}" if table else name,
                "node": table or golden[0],
                "field": name,
                "label": f"Golden input · {name}",
                "num": True,
                "sample": 0,
            })

        fields.append({
            "id": entry["id"],
            "name": entry["node"].name,
            "node": entry["table"],
            "dtype": _dtype_for(entry["node"]),
            "owner": _owner_for(entry["table"]),
            "classification": "Confidential — Financial",
            "quality": "N/A · 0 controls",
            "golden": golden,
            "blurb": f"Dependency trace for {entry['table']}.{entry['node'].name} from its golden inputs.",
            "inputs": inputs,
            "steps": steps,
        })
    return fields


def _describe_transform(fn: FieldNode) -> str:
    if fn.expression:
        return f"{fn.name} = {fn.expression}"
    return "Passthrough field (carried unchanged)."


def _job_for(table: str, is_last: bool) -> str:
    if is_last:
        return f"build_{table.lower()}"
    return f"stage_{table.lower()}"


def _dtype_for(fn: FieldNode) -> str:
    expr = fn.expression or ""
    if re.search(r"SUM|MEAN|MAX|MIN", expr, re.IGNORECASE) or re.search(r"[-+*/]", expr):
        return "DECIMAL(18,2)"
    if re.search(r"['\"]", expr):
        return "VARCHAR(140)"
    return "N/A"


def _owner_for(table: str) -> str:
    return f"{table} steward"


def build_payload(program: SASProgram) -> Dict[str, Any]:
    index = ProgramIndex(program)
    graph = build_nodes_edges(program)
    fields = build_fields(program, index)
    # Order registers by layer column so the sidebar reads source -> sink.
    observed = {n["register"]: n["col"] for n in graph["N"]}
    ordered = sorted(observed.keys(), key=lambda r: observed[r])
    stats = {
        "traced_fields": len(fields),
        "golden_sources": sum(1 for n in graph["N"] if n["golden"]),
        "registers": len(ordered),
        "datasets": len(graph["N"]),
    }
    return {
        "N": graph["N"],
        "E": graph["E"],
        "LAYERS": graph["LAYERS"],
        "registers": ordered,
        "F": fields,
        "stats": stats,
    }
