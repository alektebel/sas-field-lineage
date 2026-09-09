"""
Deterministic *fact packets* about a single field, plus the canonical plain-
English rendering of those facts.

This is the single source of truth shared by:
  * the SLM explainer (training episodes are rendered with `render_answer`,
    so gold answers are correct by construction against the parser's graph),
  * the explorer's /api/explain fallback (same renderer when no SLM is up),
  * the SLM evaluation harness (expected entities come from the same facts).

A "fact packet" is a small JSON document describing ONE question about ONE
field (construction trace, downstream fate, or affectedness). Packets contain
only raw lineage facts (fields, formulas, inputs) — the model's job is purely
to verbalise them faithfully.
"""

from __future__ import annotations

import json
import random
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

from .payload import ProgramIndex, _walk_chain

SYSTEM_PROMPT = (
    "You are the SAS Field Lineage explainer. Use ONLY the FACTS given by the "
    "user; never invent tables, fields or formulas. Answer in plain English, "
    "short lines, exactly this format:\n"
    "- Construction: 'Construction trace of FIELD:' then one line per hop "
    "'n. FIELD = FORMULA (from INPUTS)' — for a carried-through field write "
    "'n. FIELD carried through unchanged (from INPUTS)' — then "
    "'Golden inputs: LIST.'\n"
    "- Downstream: 'FIELD flows into:' lines '- TO (FORMULA)', then "
    "'Terminal fields: LIST.'; or 'No downstream use: FIELD is terminal.'\n"
    "- Affectedness: start with YES or NO. YES adds 'via: A -> B -> ...' with "
    "the dependency path. NO ends with 'is not built from OTHER.'"
)

MAX_FLOWS = 10


def _fid(table: Optional[str], name: str) -> str:
    return f"{table}.{name}" if table else name


def _hop_formula(fn) -> str:
    return f"{fn.name} = {fn.expression}" if fn.expression else "passthrough"


def _hop_expr(fn) -> Optional[str]:
    return fn.expression if fn.expression else None


class FieldFacts:
    """Field-level provenance queries over a parsed program (index-backed)."""

    def __init__(self, program):
        self.program = program
        self.index = ProgramIndex(program)
        # field id -> [(upstream id)] and inverse with the consuming formula.
        self.parents: Dict[str, List[str]] = {}
        self.consumers: Dict[str, List[Tuple[str, str]]] = {}
        self._build_edges()

    # ---- graph build ---------------------------------------------------- #
    def _dep_id(self, dep, step_idx: int, step_inputs: List[str]) -> str:
        resolved = self.index.resolve_dep(dep.name, dep.table, step_idx, step_inputs)
        if resolved is not None:
            return _fid(resolved[0], resolved[1].name)
        table = dep.table or (step_inputs[0] if step_inputs else None)
        return _fid(table, dep.name)

    def _build_edges(self) -> None:
        steps = self.program.data_steps
        for e in self.index.field_entries:
            fid = e["id"]
            ds = steps[e["step_idx"]]
            fn = e["node"]
            ups: List[str] = []
            for dep in fn.dependencies:
                up = self._dep_id(dep, e["step_idx"], ds.input_tables)
                if up == fid or up in ups:
                    continue
                ups.append(up)
            self.parents[fid] = ups
            for up in ups:
                self.consumers.setdefault(up, []).append((fid, _hop_formula(fn)))
        # ids that appear as sources but are not defined here (golden inputs)
        self.up_ids: Set[str] = {u for ups in self.parents.values() for u in ups}

    def field_ids(self) -> List[str]:
        return [e["id"] for e in self.index.field_entries]

    # ---- per-field views ------------------------------------------------- #
    def hops_for(self, field_id: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Leaves-first hop list + golden input ids for a field's construction."""
        entry = self.index.resolve_field(field_id)
        if entry is None:
            return [], []
        inputs_set: Set[Tuple[str, Optional[str]]] = set()
        chain = _walk_chain(self.index, entry, inputs_set)
        hops = []
        seen: Set[Tuple[str, ...]] = set()
        for table, fn, sidx in chain:
            ds = self.program.data_steps[sidx]
            ins = sorted({self._dep_id(d, sidx, ds.input_tables) for d in fn.dependencies})
            rec = {
                "field": _fid(table, fn.name),
                "expr": _hop_expr(fn),
                "inputs": ins,
            }
            key = (rec["field"], rec["expr"], tuple(rec["inputs"]))
            if key in seen:
                continue
            seen.add(key)
            hops.append(rec)
        golden = sorted(_fid(t, n) for n, t in inputs_set)
        return hops, golden

    def downstream(self, field_id: str) -> Dict[str, Any]:
        flows = [{"to": to, "formula": formula}
                 for to, formula in self.consumers.get(field_id, [])]
        # transitive leaves via BFS with shortest paths
        prev: Dict[str, str] = {field_id: ""}
        frontier = deque([field_id])
        leaves: List[str] = []
        while frontier:
            cur = frontier.popleft()
            kids = [to for to, _ in self.consumers.get(cur, [])]
            for k in kids:
                if k in prev:
                    continue
                prev[k] = cur
                frontier.append(k)
        for n in prev:
            if n != field_id and not self.consumers.get(n):
                leaves.append(n)
        return {"flows": flows, "all": sorted(prev), "leaves": sorted(leaves)}

    def upstream_path(self, field_id: str, other_id: str) -> Optional[List[str]]:
        """Shortest dependency path other -> ... -> field, or None.
        `other` may be a golden input (appears as a source, defined nowhere)."""
        if other_id == field_id:
            return None
        if other_id not in self.parents and other_id not in self.up_ids:
            return None
        prev: Dict[str, str] = {other_id: ""}
        frontier = deque([other_id])
        child_of: Dict[str, List[str]] = {}
        for child, ups in self.parents.items():
            for up in ups:
                child_of.setdefault(up, []).append(child)
        while frontier:
            cur = frontier.popleft()
            if cur == field_id:
                break
            for nxt in child_of.get(cur, []):
                if nxt not in prev:
                    prev[nxt] = cur
                    frontier.append(nxt)
        if field_id not in prev:
            return None
        path = [field_id]
        while path[-1] != other_id:
            path.append(prev[path[-1]])
        return list(reversed(path))

    # ---- packets + canonical answers ------------------------------------- #
    def packet(self, kind: str, field: str, other: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if self.index.resolve_field(field) is None:
            # golden inputs have no construction, but their downstream fate is knowable
            if not (kind == "downstream" and field in self.up_ids):
                return None
        if kind == "construction":
            hops, golden = self.hops_for(field)
            return {"kind": kind, "field": field, "hops": hops, "golden_inputs": golden}
        if kind == "downstream":
            d = self.downstream(field)
            return {"kind": kind, "field": field,
                    "flows": d["flows"][:MAX_FLOWS],
                    "flows_truncated": max(0, len(d["flows"]) - MAX_FLOWS),
                    "all_downstream": sorted(set(d["all"]) - {field}),
                    "terminal_fields": d["leaves"]}
        if kind == "affected":
            if not other or (self.index.resolve_field(other) is None
                             and other not in self.up_ids):
                return None
            hops, golden = self.hops_for(field)
            return {"kind": kind, "field": field, "other": other,
                    "hops": hops, "golden_inputs": golden}
        return None

    def render_answer(self, pack: Dict[str, Any]) -> str:
        kind = pack["kind"]
        field = pack["field"]
        if kind == "construction":
            lines = [f"Construction trace of {field}:"]
            for i, h in enumerate(pack["hops"], 1):
                ins = ", ".join(h["inputs"]) or "nothing (source field)"
                rhs = h.get("expr")
                head = f"{i}. {h['field']} = {rhs}" if rhs else f"{i}. {h['field']} carried through unchanged"
                lines.append(f"{head} (from {ins})")
            g = ", ".join(pack["golden_inputs"]) or "none"
            lines.append(f"Golden inputs: {g}.")
            return "\n".join(lines)
        if kind == "downstream":
            if not pack["flows"]:
                return f"No downstream use: {field} is terminal."
            lines = [f"{field} flows into:"]
            for f in pack["flows"]:
                lines.append(f"- {f['to']} ({f['formula']})")
            if pack["flows_truncated"]:
                lines.append(f"- and {pack['flows_truncated']} more fields.")
            term = ", ".join(pack["terminal_fields"]) or field
            lines.append(f"Terminal fields: {term}.")
            return "\n".join(lines)
        if kind == "affected":
            other = pack["other"]
            path = self.upstream_path(field, other)
            if path:
                return f"YES. {field} is affected by {other} via: {' -> '.join(path)}."
            return f"NO. {field} is not built from {other}."
        raise ValueError(kind)

    def expected_entities(self, pack: Dict[str, Any]) -> Tuple[Set[str], Optional[str]]:
        """(field ids a correct answer must mention, expected YES/NO or None)."""
        kind = pack["kind"]
        if kind == "construction":
            ents = {h["field"] for h in pack["hops"]} | set(pack["golden_inputs"])
            return ents, None
        if kind == "downstream":
            if not pack["flows"]:
                return {pack["field"]}, None
            direct = {f["to"] for f in pack["flows"]}
            return direct | set(pack["terminal_fields"]), None
        ents = {pack["field"], pack["other"]}
        path = self.upstream_path(pack["field"], pack["other"])
        return (ents | set(path) if path else ents), ("YES" if path else "NO")

    def packet_universe(self, pack: Dict[str, Any]) -> Set[str]:
        """Every field id visible in a packet (for leak checking)."""
        u: Set[str] = {pack["field"]}
        if "other" in pack and pack["other"]:
            u.add(pack["other"])
        for h in pack.get("hops", []):
            u.add(h["field"])
            u.update(h["inputs"])
        u.update(pack.get("golden_inputs", []))
        for f in pack.get("flows", []):
            u.add(f["to"])
        u.update(pack.get("all_downstream", []))
        u.update(pack.get("terminal_fields", []))
        return u


def user_message(pack: Dict[str, Any], question: str) -> str:
    return (f"QUESTION: {question}\n"
            f"FACTS: {json.dumps(pack, separators=(',', ':'), ensure_ascii=False)}")


_QUESTION_KINDS = ("construction", "downstream", "affected")


def make_question(kind: str, field: str, other: Optional[str], rng: random.Random) -> str:
    if kind == "construction":
        return rng.choice([
            f"How is {field} constructed?",
            f"Show the construction trace of {field}.",
            f"Where does {field} come from, step by step?",
            f"Explain how the pipeline builds {field}.",
        ])
    if kind == "downstream":
        return rng.choice([
            f"What happens to {field} further down the pipeline?",
            f"Which later fields use {field}?",
            f"Explain the downstream impact of {field}.",
            f"Where does {field} flow to?",
        ])
    return rng.choice([
        f"Is {field} affected by {other}?",
        f"Does {other} influence {field}?",
        f"Would a change in {other} propagate to {field}? Answer YES or NO.",
        f"Check whether {field} depends on {other}.",
    ])
