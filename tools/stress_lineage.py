#!/usr/bin/env python3
"""
Stress-test the lineage explorer against real-world SAS programs.

For each *.sas file in the corpus it parses the program, builds the explorer
payload (nodes/edges/fields/layers), then runs a value trace from the deepest
terminal field back through the golden inputs. It reports per-file timing,
size and stress metrics, and flags any file that crashes a stage.

Corpus (by default):
  - this repo's examples/              (self-contained demos)
  - sas-debugger/vendor/sas_samples + data/sas   (real IRB/IFRS9 bank pipelines)
  - regllm/data/sas + data/samples     (same lineage style)
  - any directory passed with --add    (e.g. the scraped public-SAS corpus)

Run:
    PYTHONPATH=src python3 tools/stress_lineage.py --add /tmp/opencode/sas_corpus --report /tmp/opencode/stress_report.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sas_lineage.parser import SASParser           # noqa: E402
from sas_lineage.ui.payload import build_payload, ProgramIndex  # noqa: E402
from sas_lineage.ui.trace import run_field_trace   # noqa: E402


def collect_inputs(add: list[str]) -> list[Path]:
    seen: set[Path] = set()
    roots: list[Path] = []

    roots += sorted(REPO_ROOT.glob("examples/*.sas"))
    for sibling in ("sas-debugger", "regllm", "dqc-poc"):
        base = REPO_ROOT.parent / sibling
        if base.is_dir():
            roots += sorted(base.glob("vendor/sas_samples/*.sas"))
            roots += sorted(base.glob("data/sas/**/*.sas"))
            roots += sorted(base.glob("data/samples/*.sas"))
    for a in add:
        p = Path(a).expanduser().resolve()
        if p.is_dir():
            roots += sorted(p.glob("**/*.sas"))
        elif p.exists():
            roots.append(p)

    out = []
    for r in roots:
        try:
            rp = r.resolve()
        except Exception:
            continue
        if rp not in seen and rp.suffix.lower() == ".sas":
            seen.add(rp)
            out.append(rp)
    return out


def seed_values(payload) -> dict:
    """Seed a representative value for every golden input of a field."""
    vals = {}
    if not payload.get("F"):
        return vals
    # Deepest chain = field with most steps.
    f = max(payload["F"], key=lambda x: len(x.get("steps", [])))
    for i in f.get("inputs", []):
        vals[i["key"]] = 1 if i.get("num", True) else "x"
    return vals


def run_one(path: Path) -> dict:
    code = path.read_bytes()
    text = code.decode("utf-8", errors="replace")
    lines = code.count(b"\n")

    rec = {
        "file": str(path), "bytes": len(code), "lines": lines,
        "data_steps": text.count("\n") + 0,  # refined below after parse
    }

    try:
        t0 = time.perf_counter()
        program = SASParser().parse(text)
        t_parse = (time.perf_counter() - t0) * 1000
    except Exception as exc:
        rec.update({"status": "PARSE_ERROR", "error": str(exc)[:200]})
        return rec

    rec.update({
        "data_steps": len(program.data_steps),
        "proc_steps": len(program.proc_steps),
        "tables": len(program.get_tables()),
    })

    try:
        t0 = time.perf_counter()
        payload = build_payload(program)
        t_payload = (time.perf_counter() - t0) * 1000
    except Exception as exc:
        rec.update({"status": "PAYLOAD_ERROR", "error": str(exc)[:200]})
        return rec

    # Must be JSON-serialisable so the browser can consume it.
    try:
        serial = len(json.dumps(payload))
    except (TypeError, ValueError) as exc:
        rec.update({"status": "SERIAL_ERROR", "error": str(exc)[:200]})
        return rec

    fields = payload["F"]
    n_steps = max((len(f.get("steps", [])) for f in fields), default=0)

    # Value trace on the deepest chain (robustness only — not correctness).
    rows = []
    try:
        if fields:
            idx = ProgramIndex(program)
            vals = seed_values(payload)
            target = max(fields, key=lambda x: len(x.get("steps", [])))["id"]
            t0 = time.perf_counter()
            rows = run_field_trace(target, vals, idx)
            t_trace = (time.perf_counter() - t0) * 1000
        else:
            t_trace = 0.0
    except Exception as exc:
        rec.update({"status": "TRACE_ERROR", "error": str(exc)[:200]})
        return rec

    rec.update({
        "status": "OK",
        "parse_ms": round(t_parse, 2),
        "payload_ms": round(t_payload, 2),
        "trace_ms": round(t_trace, 2),
        "json_bytes": serial,
        "nodes": len(payload["N"]),
        "edges": len(payload["E"]),
        "fields": len(fields),
        "layers": len(payload["LAYERS"]),
        "registers": len(payload.get("registers", [])),
        "max_chain_steps": n_steps,
        "trace_rows": len(rows),
    })
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", action="append", default=[], help="Extra dir/file to add to corpus")
    ap.add_argument("--report", default="/tmp/opencode/stress_report.json")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    inputs = collect_inputs(args.add)
    print(f"Corpus: {len(inputs)} SAS programs\n")

    results = []
    for path in inputs:
        rec = run_one(path)
        results.append(rec)
        if not args.quiet:
            ok = rec["status"] == "OK"
            ext = (f"{rec.get('fields', '-')} fields, {rec.get('nodes', '-')} nodes, "
                   f"{rec.get('edges', '-')} edges, {rec.get('max_chain_steps', '-')} chain, "
                   f"parse {rec.get('parse_ms', '-')}ms, payload {rec.get('payload_ms', '-')}ms, "
                   f"trace {rec.get('trace_ms', '-')}ms") if ok else rec.get("error", "")
            print(f"  [{'OK ' if ok else 'ERR'}] {path.name:44} {rec['lines']:>6}L  {ext}")

    ok = [r for r in results if r["status"] == "OK"]
    bad = [r for r in results if r["status"] != "OK"]
    total_bytes = sum(r["bytes"] for r in results)
    total_lines = sum(r["lines"] for r in results)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(results), "ok": len(ok), "failed": len(bad),
        "total_bytes": total_bytes, "total_lines": total_lines,
        "max_chain_steps": max((r.get("max_chain_steps", 0) for r in ok), default=0),
        "max_fields": max((r.get("fields", 0) for r in ok), default=0),
        "max_nodes": max((r.get("nodes", 0) for r in ok), default=0),
        "slowest_parse": sorted(ok, key=lambda r: -r.get("parse_ms", 0))[:5],
        "failures": bad,
        "results": results,
    }
    Path(args.report).write_text(json.dumps(report, indent=2))

    print(f"\n{'=' * 70}")
    print(f"DONE: {len(ok)}/{len(results)} OK  |  {total_bytes:,} bytes  {total_lines:,} lines")
    if bad:
        print(f"FAILURES ({len(bad)}):")
        for r in bad:
            print(f"  - {Path(r['file']).name} :: {r['status']} :: {r.get('error', '')[:120]}")
    if ok:
        mx = max(ok, key=lambda r: (r.get("fields", 0), r.get("max_chain_steps", 0)))
        print(f"Largest: {Path(mx['file']).name} — {mx['fields']} fields, {mx['nodes']} nodes, "
              f"{mx['max_chain_steps']} chain steps, payload json {mx['json_bytes']:,}B")
    print(f"Report: {args.report}")


if __name__ == "__main__":
    main()
