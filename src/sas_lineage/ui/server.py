"""
Web explorer server — a zero-dependency (stdlib-only) HTTP server for the
"Field Lineage & Golden Source Explorer" web app.

Endpoints
---------
GET  /             -> explorer.html (the web app)
GET  /api/demo     -> payload for the bundled demo SAS program
POST /api/parse    -> {"code": "...", "expand_macros": false} -> payload for that SAS program
POST /api/import   -> {"filename": "...", "content_b64": "...", "expand_macros": false}
                      -> payload for an uploaded .egp/archive, plus "source" (the
                         extracted SAS) and "import" ({format, programs, chars})
POST /api/run      -> {"field": "table.name", "vals": {...}} -> per-hop value rows
GET  /api/tables   -> persistent-library table inventory for the last parsed program
POST /api/tables   -> {"code": "..."} -> persistent-library table inventory
GET  /api/tables.xlsx  -> download that report as a workbook
POST /api/tables.xlsx  -> {"code": "..."} -> download that report as a workbook
                      (macros/prefixes always resolved; unresolved names and
                       parser warnings are included)
POST /api/explain  -> {"field": "table.name", "kind": "construction|downstream|affected",
                       "other": "table.name"} -> {answer, source, question, packet}
                       (source: "model" if the SLM service answered within the fact
                       universe, else "deterministic" engine rendering; SLM_URL env,
                       default http://127.0.0.1:8020 served by ../sas-reconcile-slm)

Run:
    python -m sas_lineage.ui.server            # http://127.0.0.1:8010
    python -m sas_lineage.ui.server --port 9000
    python -m sas_lineage.ui.server --demo examples/sales_analysis.sas
"""

from __future__ import annotations

import argparse
import base64
import binascii
import io
import json
import mimetypes
import os
import random
import re
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

from ..parser import SASParser, extract_sas
from ..parser.preprocessor import expand_for_report
from ..report import build_inventory, inventory_sheets, write_xlsx
from .facts import FieldFacts, SYSTEM_PROMPT, make_question, user_message
from .payload import build_payload, ProgramIndex
from .trace import run_field_trace

STATIC_DIR = Path(__file__).resolve().parent / "static"
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Default demo program: the shipped sales example, or an embedded fallback.
_EMBEDDED_DEMO = """/* Example SAS Code - Sales Analysis */
DATA raw_sales;
    SET input_data;
    revenue = quantity * price;
    discount_amount = revenue * discount_rate;
RUN;

DATA final_sales;
    SET raw_sales;
    net_revenue = revenue - discount_amount;
    profit = net_revenue - cost;
    profit_margin = profit / net_revenue;
RUN;

DATA summary;
    SET final_sales;
    total_profit = SUM(profit);
    avg_margin = MEAN(profit_margin);
RUN;
"""

# --------------------------------------------------------------------------- #
# In-memory parse state (the server holds the last parsed program).
# --------------------------------------------------------------------------- #
_lock = threading.Lock()
_program = None
_index: ProgramIndex | None = None
_facts: Optional[FieldFacts] = None
_last_code: str = ""
_last_expand: bool = False
_rng = random.Random(17)
SLM_URL = os.environ.get("SLM_URL", "http://127.0.0.1:8020")
# A dotted name in a model answer. It must match the *whole* chain: now that
# two-level table names are kept, a field id is ``libref.member.field``, and a
# two-part pattern captures only ``libref.member`` -- a token that is never in
# the universe, so every model answer fails the leak check and the SLM is
# silently switched off for any program that uses librefs.
_FIELD_TOKEN_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")


def _demo_code() -> str:
    fallback = PROJECT_ROOT / "examples" / "sales_analysis.sas"
    try:
        if fallback.exists():
            return fallback.read_text(encoding="utf-8")
    except Exception:
        pass
    return _EMBEDDED_DEMO


def _parse(code: str, expand_macros: bool = False) -> Dict[str, Any]:
    global _program, _index, _facts, _last_code, _last_expand
    with _lock:
        _last_code = code
        _last_expand = expand_macros
        _program = SASParser().parse(code, expand_macros=expand_macros)
        _index = ProgramIndex(_program)
        _facts = FieldFacts(_program)
        return build_payload(_program)


def _import(filename: str, content_b64: str, expand_macros: bool = False) -> Dict[str, Any]:
    """Extract SAS from an uploaded .egp/archive and parse it for lineage."""
    try:
        data = base64.b64decode(content_b64, validate=False)
    except (binascii.Error, ValueError) as exc:
        return {"error": f"Invalid upload: {exc}"}
    source, info = extract_sas(data)
    info = dict(info)
    info["filename"] = filename
    payload = _parse(source, expand_macros)
    payload["source"] = source
    payload["import"] = info
    if not source.strip():
        payload.setdefault("warnings", []).insert(0, {
            "message": f"No SAS code found in '{filename or 'upload'}' "
                       f"(detected format: {info.get('format', 'unknown')}).",
            "line": None, "statement": None, "kind": "import",
        })
    return payload


def _parse_warnings(code: str) -> list:
    """Parser warnings for ``code``, computed on the macro-resolved source."""
    try:
        return SASParser().parse(expand_for_report(code)).get_warnings()
    except Exception:
        return []


def _tables(code: str) -> Dict[str, Any]:
    """Persistent-library table inventory for ``code`` (macros always resolved)."""
    inventory = build_inventory(code)
    inventory["warnings"] = _parse_warnings(code)
    return inventory


def _tables_xlsx(code: str) -> bytes:
    inventory = build_inventory(code)
    warnings = _parse_warnings(code)
    inventory["warnings"] = warnings
    buf = io.BytesIO()
    write_xlsx(buf, inventory_sheets(inventory, warnings))
    return buf.getvalue()


def _slm_explain(system: str, user: str) -> Optional[str]:
    """Ask the SLM service for an explanation; None when it is down."""
    try:
        req = urllib.request.Request(
            SLM_URL.rstrip("/") + "/explain",
            data=json.dumps({"system": system, "user": user}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = str(body.get("text", "")).strip()
        return text or None
    except Exception:
        return None


def _explain(field_id: str, kind: str, other: str = "") -> Dict[str, Any]:
    if _facts is None or _index is None:
        return {"error": "No program loaded. Call /api/parse first."}
    pack = _facts.packet(kind, field_id, other or None)
    if pack is None:
        return {"error": f"Unknown field '{field_id}' (or 'other') for kind '{kind}'."}
    question = make_question(kind, field_id, other or None, _rng)
    deterministic = _facts.render_answer(pack)
    universe = {u.lower() for u in _facts.packet_universe(pack)}
    model_text = _slm_explain(SYSTEM_PROMPT, user_message(pack, question))
    answer, source = deterministic, "deterministic"
    if model_text:
        cited = {t.lower() for t in _FIELD_TOKEN_RE.findall(model_text)}
        if cited and cited <= universe:
            answer, source = model_text, "model"
    return {"answer": answer, "source": source, "question": question, "packet": pack,
            "deterministic": deterministic}


def _run_field(field_id: str, vals: Dict[str, Any]) -> Dict[str, Any]:
    if _index is None:
        return {"rows": [], "error": "No program loaded. Call /api/parse first."}
    try:
        rows = run_field_trace(field_id, vals, _index)
        return {"rows": rows}
    except Exception as exc:  # pragma: no cover - defensive
        return {"rows": [], "error": str(exc)}


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class _Handler(BaseHTTPRequestHandler):
    server_version = "LineageExplorer/1.0"

    # -- helpers ------------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data).encode("utf-8"), "application/json")

    def _send_file(self, status: int, body: bytes, content_type: str,
                   filename: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _code_for(self, body: Dict[str, Any]) -> str:
        code = str(body.get("code") or "")
        if code.strip():
            return code
        with _lock:
            return _last_code or _demo_code()

    def _serve_static(self, rel_path: str) -> None:
        path = STATIC_DIR / rel_path
        # Strip any query string and traversal.
        path = Path(unquote(str(path)))
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if not str(resolved).startswith(str(STATIC_DIR.resolve())):
            self._send(403, b"Forbidden", "text/plain; charset=utf-8")
            return
        if path.is_dir():
            path = path / "index.html"
        if not path.exists():
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(200, path.read_bytes(), ctype + "; charset=utf-8" if ctype.startswith("text/") else ctype)

    # -- verbs --------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/explorer.html":
            self._serve_static("explorer.html")
        elif parsed.path == "/api/demo":
            payload = _parse(_demo_code())
            self._send_json(200, payload)
        elif parsed.path == "/api/tables":
            with _lock:
                code = _last_code or _demo_code()
            self._send_json(200, _tables(code))
        elif parsed.path == "/api/tables.xlsx":
            with _lock:
                code = _last_code or _demo_code()
            self._send_file(
                200, _tables_xlsx(code),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "persistent_library_tables.xlsx",
            )
        elif parsed.path.startswith("/api/"):
            self._send_json(404, {"error": "Unknown API endpoint"})
        else:
            rel = parsed.path.lstrip("/")
            self._serve_static(rel)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/parse":
            body = self._read_body()
            code = body.get("code", "")
            if not code:
                self._send_json(400, {"error": "Missing 'code'"})
                return
            payload = _parse(code, bool(body.get("expand_macros", False)))
            self._send_json(200, payload)
        elif parsed.path == "/api/import":
            body = self._read_body()
            content = str(body.get("content_b64") or "")
            if not content:
                self._send_json(400, {"error": "Missing 'content_b64'"})
                return
            result = _import(
                str(body.get("filename") or ""), content,
                bool(body.get("expand_macros", False)),
            )
            if "error" in result and "source" not in result:
                self._send_json(400, result)
                return
            self._send_json(200, result)
        elif parsed.path == "/api/tables":
            self._send_json(200, _tables(self._code_for(self._read_body())))
        elif parsed.path == "/api/tables.xlsx":
            self._send_file(
                200, _tables_xlsx(self._code_for(self._read_body())),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "persistent_library_tables.xlsx",
            )
        elif parsed.path == "/api/run":
            body = self._read_body()
            field = body.get("field", "")
            vals = body.get("vals", {})
            self._send_json(200, _run_field(field, vals))
        elif parsed.path == "/api/explain":
            body = self._read_body()
            field = body.get("field", "")
            kind = body.get("kind", "construction")
            other = body.get("other", "")
            if not field:
                self._send_json(400, {"error": "Missing 'field'"})
                return
            self._send_json(200, _explain(field, kind, other))
        else:
            self._send_json(404, {"error": "Unknown API endpoint"})

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep the console quiet unless --verbose is passed.
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)


def run_server(host: str = "127.0.0.1", port: int = 8010, verbose: bool = False) -> None:
    server = ThreadingHTTPServer((host, port), _Handler)
    server.daemon_threads = True
    server.verbose = verbose
    print(f"Field Lineage & Golden Source Explorer")
    print(f"  Serving on  http://{host}:{port}")
    print(f"  Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


def main(argv: Tuple[str, ...] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Field Lineage & Golden Source Explorer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    run_server(args.host, args.port, args.verbose)


if __name__ == "__main__":
    main()
