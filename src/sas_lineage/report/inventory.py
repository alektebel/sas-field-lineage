"""
Inventory of tables written to SAS *persistent* libraries.

The field-lineage parser intentionally tracks only what it needs for lineage
and captures a single-token ``DATA`` target, so it cannot answer "which tables
does this program persist, and where?". This module scans the same statement
stream with a table-oriented lens and:

* finds every ``LIBNAME`` declaration (libref, engine, path),
* finds every persistent write — ``DATA lib.table``, ``PROC SQL CREATE
  TABLE/VIEW``, and any ``OUT=`` / ``BASE=`` output of a PROC step,
* resolves ``&macro`` / ``%let`` names first (via
  :func:`~sas_lineage.parser.preprocessor.expand_for_report`) so libraries and
  ``prefix_`` names built from macros are reported by their resolved name,
* keeps anything it could not resolve (``&lib.table``) as a flagged row rather
  than dropping it.

A table counts as persistent when it is written to any non-``WORK`` libref,
whether or not that libref is declared with ``LIBNAME`` in the source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..parser.preprocessor import expand_audited
from ..parser.sas_parser import SASParser

__all__ = [
    "LibraryRef",
    "PersistentTable",
    "build_inventory",
    "inventory_rows",
    "inventory_sheets",
    "assurance",
]

_LIBNAME_RE = re.compile(r"^LIBNAME\s+([A-Za-z_]\w*)\s*(.*)$", re.IGNORECASE | re.DOTALL)
_DATA_RE = re.compile(r"^DATA\s+(.+)$", re.IGNORECASE | re.DOTALL)
_CREATE_RE = re.compile(r"^\s*CREATE\s+(TABLE|VIEW)\s+([\w.&%]+)", re.IGNORECASE)
_PROC_RE = re.compile(r"^PROC\s+(\w+)", re.IGNORECASE)
_TERMINATOR_RE = re.compile(r"^(?:RUN|QUIT)\b", re.IGNORECASE)
_SET_MERGE_RE = re.compile(r"^(?:SET|MERGE|UPDATE)\s+(.+)", re.IGNORECASE | re.DOTALL)
_OUT_RE = re.compile(r"\b(?:OUT|OUTPUT|BASE)\s*=\s*([A-Za-z_&%][\w.&%]*)", re.IGNORECASE)
_DATA_OPT_RE = re.compile(r"\bDATA\s*=\s*([A-Za-z_&%][\w.&%]*)", re.IGNORECASE)
_FROM_RE = re.compile(r"\bFROM\s+([A-Za-z_&%][\w.&%]*)", re.IGNORECASE)
_DATASET_TOKEN_RE = re.compile(r"^[A-Za-z_&%][\w.&%]*$")
_MEMBER_OPTIONS_RE = re.compile(r"\(.*?\)")
_WS_RE = re.compile(r"\s+")

_CREATED_BY = {
    "DATA": "DATA step",
    "SQL": "PROC SQL",
    "SORT": "PROC SORT",
    "MEANS": "PROC MEANS",
    "SUMMARY": "PROC SUMMARY",
    "TABULATE": "PROC TABULATE",
    "TRANSPOSE": "PROC TRANSPOSE",
    "APPEND": "PROC APPEND",
    "RANK": "PROC RANK",
    "UNIVARIATE": "PROC UNIVARIATE",
    "FREQ": "PROC FREQ",
    "REPORT": "PROC REPORT",
}


@dataclass
class LibraryRef:
    """A SAS libref, declared with ``LIBNAME`` or merely referenced."""

    libref: str
    engine: str = ""
    path: str = ""
    declared: bool = False
    source_line: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "libref": self.libref,
            "engine": self.engine,
            "path": self.path,
            "declared": self.declared,
            "source_line": self.source_line,
        }


@dataclass
class PersistentTable:
    """One persistent table (or view) written by the program."""

    library: str
    table: str
    created_by: str
    proc: str
    statement: str
    source_line: Optional[int] = None
    input_tables: str = ""
    macro_built: bool = False
    resolved: bool = True
    lib_engine: str = ""
    lib_path: str = ""
    declared: bool = False
    # Data-flow stage this table belongs to ("division"/flux).
    division: str = ""
    division_col: int = 0

    @property
    def name(self) -> str:
        return f"{self.library}.{self.table}"

    def to_dict(self) -> Dict[str, object]:
        return {
            "division": self.division,
            "division_col": self.division_col,
            "library": self.library,
            "table": self.table,
            "name": self.name,
            "created_by": self.created_by,
            "proc": self.proc,
            "input_tables": self.input_tables,
            "statement": self.statement,
            "source_line": self.source_line,
            "macro_built": self.macro_built,
            "resolved": self.resolved,
            "lib_engine": self.lib_engine,
            "lib_path": self.lib_path,
            "declared_library": self.declared,
        }


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _tokenize(text: str) -> List[Tuple[str, int]]:
    """Statement stream ``(text, line)`` — comments and datalines handled."""
    return SASParser()._tokenize(text)


def _collapse(stmt: str, limit: int = 240) -> str:
    text = _WS_RE.sub(" ", stmt).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _parse_libname(rest: str) -> Tuple[str, str]:
    """Return ``(engine, path)`` for the text after ``LIBNAME libref``."""
    rest = rest.strip()
    if not rest or rest.upper() in ("CLEAR", "REFRESH"):
        return "", ""
    quoted = re.search(r"(['\"])(.*?)\1", rest)
    if quoted:
        path = quoted.group(2)
        before = rest[: quoted.start()].strip()
        engine = before.split()[0].upper() if before else "BASE"
        return engine or "BASE", path
    tokens = rest.split()
    if not tokens:
        return "", ""
    engine = tokens[0].upper()
    path = tokens[1] if len(tokens) > 1 else ""
    return engine, path


def _data_targets(rest: str) -> List[str]:
    """Persistent dataset targets of a ``DATA`` statement, ``lib.table`` kept."""
    rest = rest.split("/", 1)[0]
    rest = _MEMBER_OPTIONS_RE.sub(" ", rest)
    out: List[str] = []
    for token in rest.split():
        token = token.strip().rstrip(",")
        if not token or token.upper() == "_NULL_":
            continue
        if _DATASET_TOKEN_RE.match(token):
            out.append(token)
    return out


# Pipeline stages a table can land in, mirroring the explorer's registers.
_DIVISION_LABELS = ["Golden sources", "Landing", "Curated", "Marts", "Reporting"]


def _division_label(col: int) -> str:
    if 0 <= col < len(_DIVISION_LABELS):
        return _DIVISION_LABELS[col]
    return f"Stage {col + 1}"


def _split_inputs(inputs: str) -> List[str]:
    return [token.strip() for token in re.split(r"[,\s]+", inputs or "") if token.strip()]


def _assign_divisions(rows: List["PersistentTable"]) -> List[Dict[str, object]]:
    """Assign each table a division from its position in the data-flow graph.

    Edges run from every input table to the table it feeds; a table's division
    is its longest distance from a source, i.e. the "flux" stage it appears in.
    """
    producers: Dict[str, set] = {}
    for row in rows:
        for source in _split_inputs(row.input_tables):
            if source.lower() == row.name.lower():
                continue
            producers.setdefault(row.name, set()).add(source)

    column: Dict[str, int] = {}

    def longest(name: str, seen: set) -> int:
        if name in column:
            return column[name]
        if name in seen:
            return 0
        seen = seen | {name}
        best = 0
        for parent in producers.get(name, ()):
            best = max(best, 1 + longest(parent, seen))
        column[name] = best
        return best

    for row in rows:
        longest(row.name, set())

    counts: Dict[str, Dict[str, object]] = {}
    for row in rows:
        col = column.get(row.name, 0)
        row.division_col = col
        row.division = _division_label(col)
        entry = counts.setdefault(row.division, {"name": row.division, "col": col, "count": 0})
        entry["count"] = int(entry["count"]) + 1
    return sorted(counts.values(), key=lambda e: (int(e["col"]), str(e["name"])))


def _split_persistent(target: str) -> Optional[Tuple[str, str]]:
    """Split ``lib.table``; return None for temporary (WORK / unqualified)."""
    target = target.strip().strip(";").split("(", 1)[0].strip()
    if not target or target.upper().startswith("_NULL_"):
        return None
    if "." not in target:
        return None
    library, _, table = target.partition(".")
    table = table.lstrip(".")
    if not library or not table:
        return None
    if library.upper() == "WORK":
        return None
    return library, table


class _Scanner:
    def __init__(self, libraries: Dict[str, LibraryRef], raw_lower: str):
        self.libraries = libraries
        self.raw_lower = raw_lower
        self.rows: List[PersistentTable] = []
        self._open: List[PersistentTable] = []
        self._open_inputs: List[str] = []
        self._proc: Optional[str] = None
        self._proc_input = ""

    # -- row construction -------------------------------------------------- #
    def _library(self, libref: str) -> LibraryRef:
        ref = self.libraries.get(libref.lower())
        if ref is None:
            ref = LibraryRef(libref=libref, declared=False)
            self.libraries[libref.lower()] = ref
        return ref

    def _add(self, target: str, created_by: str, proc: str, stmt: str,
             line: int, inputs: str = "") -> None:
        parts = _split_persistent(target)
        if parts is None:
            return
        library, table = parts
        ref = self._library(library)
        name = f"{library}.{table}"
        row = PersistentTable(
            library=library,
            table=table,
            created_by=created_by,
            proc=proc,
            statement=_collapse(stmt),
            source_line=line,
            input_tables=inputs,
            resolved=not re.search(r"[&%]", target),
            macro_built=bool(re.search(r"[&%]", target)) or name.lower() not in self.raw_lower,
            lib_engine=ref.engine,
            lib_path=ref.path,
            declared=ref.declared,
        )
        self.rows.append(row)

    def _flush(self) -> None:
        inputs = ", ".join(dict.fromkeys(self._open_inputs))
        for row in self._open:
            row.input_tables = inputs
        self.rows.extend(self._open)
        self._open = []
        self._open_inputs = []

    # -- statement handling ------------------------------------------------ #
    def feed(self, stmt: str, line: int) -> None:
        stmt = stmt.strip()
        if not stmt:
            return
        upper = stmt.upper()

        lib = _LIBNAME_RE.match(stmt)
        if lib:
            engine, path = _parse_libname(lib.group(2))
            if path or engine:
                self.libraries[lib.group(1).lower()] = LibraryRef(
                    libref=lib.group(1), engine=engine, path=path,
                    declared=True, source_line=line,
                )
            return

        if _PROC_RE.match(stmt):
            self._flush()
            self._proc = _PROC_RE.match(stmt).group(1).upper()
            self._proc_input = ""
            dm = _DATA_OPT_RE.search(stmt)
            if dm:
                self._proc_input = dm.group(1)
            for out in _OUT_RE.finditer(stmt):
                self._add(out.group(1), self._created_by(), self._proc, stmt, line,
                          self._proc_input)
            return

        if _DATA_RE.match(stmt):
            self._flush()
            self._proc = "DATA"
            for target in _data_targets(_DATA_RE.match(stmt).group(1)):
                parts = _split_persistent(target)
                if parts is None:
                    continue
                library, table = parts
                ref = self._library(library)
                name = f"{library}.{table}"
                self._open.append(PersistentTable(
                    library=library, table=table, created_by="DATA step", proc="DATA",
                    statement=_collapse(stmt), source_line=line,
                    resolved=not re.search(r"[&%]", target),
                    macro_built=bool(re.search(r"[&%]", target)) or name.lower() not in self.raw_lower,
                    lib_engine=ref.engine, lib_path=ref.path, declared=ref.declared,
                ))
            return

        create = _CREATE_RE.match(stmt)
        if create:
            self._flush()
            kind = "PROC SQL CREATE TABLE" if create.group(1).upper() == "TABLE" \
                else "PROC SQL CREATE VIEW"
            froms = ", ".join(dict.fromkeys(_FROM_RE.findall(stmt)))
            self._add(create.group(2), kind, "SQL", stmt, line, froms)
            return

        if self._open and _SET_MERGE_RE.match(stmt):
            for token in _SET_MERGE_RE.match(stmt).group(1).split():
                token = token.strip().rstrip(",")
                if _DATASET_TOKEN_RE.match(token):
                    self._open_inputs.append(token)
            return

        if self._proc and _OUT_RE.search(stmt):
            dm = _DATA_OPT_RE.search(stmt)
            inputs = dm.group(1) if dm else self._proc_input
            for out in _OUT_RE.finditer(stmt):
                self._add(out.group(1), self._created_by(), self._proc, stmt, line, inputs)
            return

        if _TERMINATOR_RE.match(stmt):
            self._flush()
            self._proc = None
            self._proc_input = ""

    def _created_by(self) -> str:
        return _CREATED_BY.get(self._proc or "", f"PROC {self._proc}" if self._proc else "SAS write")


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def build_inventory(
    code: str,
    include_base: Optional[str] = None,
    expand: bool = True,
) -> Dict[str, object]:
    """Scan ``code`` and return persistent libraries and the tables written.

    Macros are always resolved first (``%let``/``&`` at minimum, the supported
    ``%macro``/``%do``/``%if`` subset when possible). Set ``expand=False`` only
    to inspect raw names.
    """
    raw_lower = _WS_RE.sub(" ", code).lower()
    if expand:
        expanded, audit = expand_audited(code, include_base)
    else:
        expanded = code
        audit = {
            "complete": False, "residual_refs": [], "residual_count": 0,
            "macros_defined": [], "symbols_defined": [],
            "macro_invocations": 0, "macro_invocations_unresolved": [],
            "truncated": False,
        }
    statements = _tokenize(expanded)

    libraries: Dict[str, LibraryRef] = {}
    scanner = _Scanner(libraries, raw_lower)
    for stmt, line in statements:
        scanner.feed(stmt, line)
    scanner._flush()

    # Deduplicate rows by (library, table, created_by, source_line): a PROC step
    # can surface the same OUT= more than once, and a table may be rewritten.
    seen = set()
    tables: List[PersistentTable] = []
    for row in scanner.rows:
        key = (row.library.lower(), row.table.lower(), row.created_by, row.source_line)
        if key in seen:
            continue
        seen.add(key)
        tables.append(row)
    divisions = _assign_divisions(tables)
    tables.sort(key=lambda r: (r.division_col, r.library.lower(), r.table.lower(),
                               r.source_line or 0))

    declared = [ref for ref in libraries.values() if ref.declared]
    stats = {
        "tables": len(tables),
        "libraries": len(libraries),
        "declared_libraries": len(declared),
        "macro_built": sum(1 for r in tables if r.macro_built),
        "unresolved": sum(1 for r in tables if not r.resolved),
        "divisions": len(divisions),
    }
    return {
        "libraries": [ref.to_dict() for ref in sorted(libraries.values(),
                                                       key=lambda r: r.libref.lower())],
        "tables": [row.to_dict() for row in tables],
        "divisions": divisions,
        "audit": audit,
        "stats": stats,
    }


def _bare(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower()


def parsed_outputs(code: str, expand: bool = True) -> List[str]:
    """Every dataset the parser saw being written (persistent *and* WORK)."""
    source = expand_audited(code)[0] if expand else code
    program = SASParser().parse(source)
    outputs = [ds.output_table for ds in program.data_steps if ds.output_table]
    outputs += [ps.output_table for ps in program.proc_steps if ps.output_table]
    return outputs


def assurance(inventory: Dict[str, object],
              manifest_tables: Optional[List[str]] = None,
              parsed_tables: Optional[List[str]] = None) -> Dict[str, object]:
    """Reconcile the report against the substitution audit and an EGP manifest.

    ``substitution_complete`` is True only when the expander resolved every
    macro call and every ``&``/``%`` reference — i.e. nothing was dropped
    silently. When ``manifest_tables`` (the ``tables_produced`` list from an
    EGP ``manifest.json``) is supplied, each expected table is classified as:

    * ``matched`` — present in the persistent-library report,
    * ``parsed_not_persistent`` — the parser saw it, but it lands in ``WORK``,
    * ``missing`` — never seen at all (a genuine gap).

    Matching is by bare table name because the manifest lists names without a
    library while the report keeps ``lib.table``.
    """
    persistent: Dict[str, str] = {}
    for table in inventory.get("tables", []):  # type: ignore[union-attr]
        persistent.setdefault(_bare(str(table.get("table", ""))), str(table.get("name", "")))

    seen = set(persistent)
    for name in (parsed_tables or []):
        seen.add(_bare(str(name)))

    expected = [str(t) for t in (manifest_tables or [])]
    expected_lower = {t.lower() for t in expected}
    matched: List[str] = []
    parsed_only: List[str] = []
    missing: List[str] = []
    for name in expected:
        key = name.lower()
        if key in persistent:
            matched.append(name)
        elif key in seen:
            parsed_only.append(name)
        else:
            missing.append(name)
    extra = [name for key, name in persistent.items() if key not in expected_lower]

    audit = inventory.get("audit", {}) or {}
    return {
        "substitution_complete": bool(audit.get("complete", True)),
        "unresolved": list(audit.get("residual_refs", [])),
        "macros_defined": len(audit.get("macros_defined", [])),
        "symbols_defined": len(audit.get("symbols_defined", [])),
        "macro_invocations": audit.get("macro_invocations", 0),
        "manifest_checked": bool(expected),
        "matched": matched,
        "parsed_not_persistent": parsed_only,
        "missing": missing,
        "extra": extra,
        "reported": len(persistent),
        "expected": len(expected),
        "accounted": len(matched) + len(parsed_only),
    }


_TABLE_COLUMNS = [
    ("division", "Division"),
    ("library", "Library"),
    ("table", "Table"),
    ("name", "Name"),
    ("created_by", "Created by"),
    ("input_tables", "Input tables"),
    ("source_line", "Line"),
    ("macro_built", "Macro-built"),
    ("resolved", "Resolved"),
    ("declared_library", "LIBNAME declared"),
    ("lib_engine", "Engine"),
    ("lib_path", "Library path"),
    ("statement", "Statement"),
]

_LIBRARY_COLUMNS = [
    ("libref", "Libref"),
    ("engine", "Engine"),
    ("path", "Path"),
    ("declared", "Declared"),
    ("source_line", "Line"),
]


def inventory_rows(inventory: Dict[str, object]) -> List[List[object]]:
    """Table rows (header first) for a spreadsheet export."""
    rows: List[List[object]] = [[label for _key, label in _TABLE_COLUMNS]]
    for table in inventory.get("tables", []):  # type: ignore[union-attr]
        rows.append([_cell(table.get(key)) for key, _label in _TABLE_COLUMNS])
    return rows


def _assurance_rows(inventory: Dict[str, object],
                    manifest_tables: Optional[List[str]] = None) -> List[List[object]]:
    info = assurance(inventory, manifest_tables)
    rows: List[List[object]] = [["Check", "Result", "Detail"]]
    rows.append([
        "Macro substitution complete",
        "Yes" if info["substitution_complete"] else "No",
        ", ".join(info["unresolved"]) or "all references resolved",
    ])
    rows.append(["Macros defined", info["macros_defined"], ""])
    rows.append(["Symbols (%let) defined", info["symbols_defined"], ""])
    rows.append(["Macro invocations", info["macro_invocations"], ""])
    if info["manifest_checked"]:
        rows.append(["Manifest tables expected", info["expected"], ""])
        rows.append(["Matched (persistent)", len(info["matched"]), ", ".join(info["matched"])])
        rows.append(["Parsed but not persistent (WORK)", len(info["parsed_not_persistent"]),
                     ", ".join(info["parsed_not_persistent"])])
        rows.append(["Missing (not parsed)", len(info["missing"]), ", ".join(info["missing"])])
        rows.append(["Not in manifest", len(info["extra"]), ", ".join(info["extra"])])
    else:
        rows.append(["Manifest tables expected", 0, "no manifest in source"])
    return rows


def _rows_for_tables(tables: List[Dict[str, object]]) -> List[List[object]]:
    return [[label for _key, label in _TABLE_COLUMNS]] + [
        [_cell(table.get(key)) for key, _label in _TABLE_COLUMNS] for table in tables
    ]


def inventory_sheets(
    inventory: Dict[str, object],
    warnings: Optional[List[Dict[str, object]]] = None,
    manifest_tables: Optional[List[str]] = None,
) -> List[Tuple[str, List[List[object]]]]:
    """Workbook sheets: every table in one sheet, then the supporting sheets.

    All tables share a single ``Persistent tables`` sheet with the division
    (the data-flow stage: Golden sources -> Landing -> Curated -> Marts ->
    Reporting) as its first column. One sheet per division looks tidy and is
    worse to use: the question people ask is "where does this table sit and
    what feeds it", and splitting the answer across sheets means opening every
    one of them to sort or filter. As a column the division still groups,
    sorts and filters -- and it does so next to the library and the inputs.

    ``Libraries``, ``Summary`` and (optionally) ``Parser warnings`` follow.
    """
    tables: List[Dict[str, object]] = list(inventory.get("tables", []))  # type: ignore[arg-type]
    divisions = list(inventory.get("divisions", []))  # type: ignore[arg-type]

    lib_rows: List[List[object]] = [[label for _key, label in _LIBRARY_COLUMNS]]
    for ref in inventory.get("libraries", []):  # type: ignore[union-attr]
        lib_rows.append([_cell(ref.get(key)) for key, _label in _LIBRARY_COLUMNS])

    stats = inventory.get("stats", {})  # type: ignore[assignment]
    summary = [["Metric", "Value"]]
    for key, label in (
        ("tables", "Persistent tables"),
        ("libraries", "Libraries referenced"),
        ("declared_libraries", "Libraries declared with LIBNAME"),
        ("divisions", "Flow divisions"),
        ("macro_built", "Tables built from macros"),
        ("unresolved", "Unresolved macro names"),
    ):
        summary.append([label, stats.get(key, 0)])
    if warnings is not None:
        summary.append(["Parser warnings", len(warnings)])

    # Tables are ordered by division so the single sheet still reads
    # source -> sink without needing one tab per stage.
    order = {str(d.get("name", "")): i for i, d in enumerate(divisions)}
    ordered = sorted(tables, key=lambda t: (order.get(str(t.get("division", "")), len(order)),
                                            str(t.get("name", ""))))
    sheets: List[Tuple[str, List[List[object]]]] = [
        ("Persistent tables", _rows_for_tables(ordered)),
    ]
    sheets.append(("Libraries", lib_rows))
    sheets.append(("Summary", summary))
    sheets.append(("Assurance", _assurance_rows(inventory, manifest_tables)))
    if warnings:
        warn_rows: List[List[object]] = [["Kind", "Line", "Message", "Statement"]]
        for w in warnings:
            warn_rows.append([
                _cell(w.get("kind")), _cell(w.get("line")),
                _cell(w.get("message")), _cell(w.get("statement")),
            ])
        sheets.append(("Parser warnings", warn_rows))
    return sheets


def _cell(value: object) -> object:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value is None:
        return ""
    return value
