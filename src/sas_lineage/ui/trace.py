"""
Forward-propagate golden input values through a field's dependency chain and
report the value at *every* hop — the explorer's "value at every hop" and the
"complete trace from golden sources" view.

Expressions are evaluated with the same spirit as `lineage.evaluator` but
stand-alone (no pandas dependency): safe AST evaluation with a small set of SAS
functions (SUM/MEAN/MAX/MIN/ABS/ROUND). Values flow by field name, so a later
hop can reference an earlier derived field, mirroring a SAS DATA step.
"""

from __future__ import annotations

import ast
import operator
import re
from typing import Any, Dict, List, Optional, Tuple

from ..ast.field_ast import FieldNode, SASProgram

SAS_KEYWORDS = {
    "sum", "mean", "max", "min", "abs", "round", "put", "input", "int",
    "then", "else", "do", "end", "data", "set", "merge", "by", "run",
    "proc", "quit", "if", "and", "or", "where",
}

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_ALLOWED_CALLS = {
    "sum": lambda *a: sum(float(x) if isinstance(x, (int, float)) else 0.0 for x in a),
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "float": float,
    "int": int,
    "mean": lambda *a: (sum(float(x) if isinstance(x, (int, float)) else 0.0 for x in a) / len(a)) if a else 0,
}


def _safe_eval_node(node: ast.AST, env: Dict[str, Any]):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp):
        return _OPS[type(node.op)](_safe_eval_node(node.left, env), _safe_eval_node(node.right, env))
    if isinstance(node, ast.UnaryOp):
        return _OPS[type(node.op)](_safe_eval_node(node.operand, env))
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.Call):
        fn_name = node.func.id if isinstance(node.func, ast.Name) else None
        fn = _ALLOWED_CALLS.get(fn_name.lower() if fn_name else None)
        if fn is None:
            raise ValueError(f"Unsupported function: {fn_name}")
        args = [_safe_eval_node(a, env) for a in node.args]
        return fn(*args)
    if isinstance(node, ast.IfExp):
        test = _safe_eval_node(node.test, env)
        return _safe_eval_node(node.body if test else node.orelse, env)
    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def _mean(value: float) -> float:
    return float(value)


def eval_expr(expression: str, env: Dict[str, Any]) -> Any:
    """Evaluate a numeric/string expression given field-name -> value env."""
    if not expression:
        return None
    # Normalise SAS function casing so AST Call handling is predictable.
    expr = expression
    for fn in ("SUM", "MEAN", "MAX", "MIN", "ABS", "ROUND"):
        expr = re.sub(rf"\b{fn}\b", fn.lower(), expr)
    # Replace qualified table.field references with the env value first.
    def qual(match):
        field = match.group(0).rsplit(".", 1)[-1]
        return f" {_render_num(env.get(field))} "
    expr = re.sub(r"[A-Za-z_]\w*\.\w+", qual, expr)

    # Parse; on any failure return the raw expression so the UI shows text.
    try:
        tree = ast.parse(expr, mode="eval")
        return _safe_eval_node(tree.body, env)
    except Exception:
        return expr


def _render_num(v: Any) -> str:
    if isinstance(v, float):
        return repr(v)
    return str(v)


def _collect_leaf_env(
    field_id: str,
    vals: Dict[str, Any],
    index,
) -> Tuple[Dict[str, Any], List[Tuple[str, ...]], List[Dict[str, Any]]]:
    """Seed the environment from the field's golden inputs.

    Returns (env, ordered_steps, inputs). ``env`` maps both ``name`` and the
    ``table.name`` key to the supplied value; ``ordered_steps`` lists the
    (table, fieldname, expression) hops leaves-first.
    """
    entry = index.resolve_field(field_id)
    if entry is None:
        return {}, [], []

    # Re-derive the same chain payload.py used, so steps and values align.
    from .payload import _walk_chain

    inputs_set = set()
    chain = _walk_chain(index, entry, inputs_set)

    env: Dict[str, Any] = {}
    inputs = []
    for name, table in sorted(inputs_set, key=lambda x: (x[0] or "", x[1] or "")):
        val = _pick(vals, table, name)
        if val is not None:
            if table:
                env[table + "." + name] = val
            env[name] = val
        inputs.append({"node": table, "field": name})
    steps = [
        (table, fn.name, fn.expression or f"{fn.name}")
        for table, fn, _idx in chain
    ]
    return env, steps, inputs


def _pick(vals: Dict[str, Any], table: Optional[str], name: str) -> Any:
    key = f"{table}.{name}" if table else name
    if key in vals and vals[key] not in (None, ""):
        return vals[key]
    if name in vals and vals[name] not in (None, ""):
        return vals[name]
    return None


def run_field_trace(field_id: str, vals: Dict[str, Any], index) -> List[Dict[str, Any]]:
    """Compute the value at every hop for a field, leaves-first.

    Returns rows: [{node, field, value, expr}] ordered source -> terminal.
    """
    env, steps, _inputs = _collect_leaf_env(field_id, vals, index)
    if not steps:
        return []
    rows = []
    for table, fname, expr in steps:
        value = eval_expr(expr, env) if expr else env.get(fname)
        # If the expression is a bare reference to another field, resolve it.
        if isinstance(value, str) and value in env:
            value = env[value]
        env[fname] = value
        rows.append({
            "node": table,
            "field": fname,
            "value": value if value is not None else "",
            "expr": expr,
        })
    return rows
