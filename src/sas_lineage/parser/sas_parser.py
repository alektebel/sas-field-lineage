"""
Simplified SAS parser using regex patterns
This parser handles common SAS DATA step and PROC step patterns
"""
import re
from typing import List, Optional, Tuple, Dict
from ..ast.field_ast import (
    FieldNode, FieldOperationType, DataStepNode, 
    ProcStepNode, SASProgram
)
from .preprocessor import preprocess_ex

# A dataset reference: ``[libref.]member`` where either part may still carry an
# unexpanded ``&``/``%`` reference that the macro pass could not resolve.
_DS_TOKEN = r"[A-Za-z_&%][\w.&%$]*"
_DATA_OPT_RE = re.compile(r"\bDATA\s*=\s*(" + _DS_TOKEN + r")", re.IGNORECASE)
_OUT_OPT_RE = re.compile(r"\bOUT(?:EST)?\s*=\s*(" + _DS_TOKEN + r")", re.IGNORECASE)
_BASE_OPT_RE = re.compile(r"\bBASE\s*=\s*(" + _DS_TOKEN + r")", re.IGNORECASE)
_SQL_CREATE_RE = re.compile(r"\bCREATE\s+(?:TABLE|VIEW)\s+(" + _DS_TOKEN + r")", re.IGNORECASE)
_SQL_INSERT_RE = re.compile(r"\bINSERT\s+INTO\s+(" + _DS_TOKEN + r")", re.IGNORECASE)
_SQL_JOIN_RE = re.compile(r"\bJOIN\s+(" + _DS_TOKEN + r")", re.IGNORECASE)
_SQL_FROM_RE = re.compile(
    r"\bFROM\s+(.*?)(?=\b(?:FROM|WHERE|GROUP|HAVING|ORDER|INNER|LEFT|RIGHT|FULL|OUTER|CROSS|JOIN|ON|UNION|EXCEPT|INTERSECT)\b|$)",
    re.IGNORECASE | re.DOTALL,
)
# DATA-step statements whose operand is a list of datasets to read.
_INPUT_STATEMENTS = {"SET", "MERGE", "UPDATE", "MODIFY"}


def _normalize_table(name: str) -> str:
    """Canonical form of a dataset reference.

    SAS dataset names are case-insensitive and an explicit ``WORK.`` libref
    names the same dataset as the bare member, so both are folded -- otherwise
    ``work.sales`` and ``sales`` become two nodes for one table. A name that
    still holds an unresolved macro reference is lowercased but otherwise kept
    verbatim, so the caller can see exactly what was not resolved.
    """
    name = name.strip().strip("()").strip().rstrip(".").lower()
    if name.startswith("work."):
        name = name[len("work."):]
    return name


def is_unresolved_table(name: str) -> bool:
    """True when a table name still carries an unexpanded macro reference."""
    return "&" in name or "%" in name


def _split_dataset_refs(text: str) -> List[str]:
    """Split a SAS dataset list into canonical table names.

    Handles ``libref.member``, dataset options in balanced parentheses
    (``(keep=a b)``, ``(in=x)``, ``(where=(y>0))``), several datasets on one
    statement, and the ``/`` that introduces step options. A bare
    ``keyword=`` token (``END=``, ``NOBS=``, ``POINT=``, ``NODUPKEY``-style
    options) terminates the list: it is an option, not a dataset.
    """
    refs: List[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n,":
            i += 1
            continue
        if ch == "/":                      # step options: nothing after is a dataset
            break
        if ch == "(":                      # dataset options of the previous name
            i = _skip_parens(text, i)
            continue
        m = re.match(_DS_TOKEN, text[i:])
        if not m:
            i += 1
            continue
        token = m.group(0)
        j = i + m.end()
        k = j
        while k < n and text[k] in " \t\r\n":
            k += 1
        if k < n and text[k] == "=":       # an option keyword, not a dataset
            break
        name = _normalize_table(token)
        if name and name not in refs:
            refs.append(name)
        i = j
    return refs


def _skip_parens(text: str, start: int) -> int:
    """Index just past the parenthesis group opening at ``start``.

    Quoted literals are skipped whole: a parenthesis inside ``where=(x="(")``
    is data, and counting it would unbalance the group and swallow whatever
    dataset came next.
    """
    depth = 0
    i, n = start, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            quote = ch
            i += 1
            while i < n and text[i] != quote:
                i += 1
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _sql_sources(stmt: str) -> List[str]:
    """Tables read by one ``PROC SQL`` statement (FROM list plus JOINs)."""
    out: List[str] = []
    for m in _SQL_FROM_RE.finditer(stmt):
        for item in m.group(1).split(","):
            item = item.strip()
            if not item or item.startswith("("):   # in-line sub-select
                continue
            first = item.split()[0]                # drop ``AS alias`` / ``alias``
            name = _normalize_table(first)
            if name and name not in out:
                out.append(name)
    for m in _SQL_JOIN_RE.finditer(stmt):
        name = _normalize_table(m.group(1))
        if name and name not in out:
            out.append(name)
    return out


# Common SAS keywords and functions that should not be treated as field references
SAS_KEYWORDS = {
    'sum', 'mean', 'max', 'min', 'count', 'put', 'input', 
    'substr', 'trim', 'left', 'right', 'upcase', 'lowcase',
    'if', 'then', 'else', 'do', 'end', 'where', 'and', 'or',
    'data', 'set', 'merge', 'by', 'run', 'proc', 'quit'
}


class SASParser:
    """
    Parser for SAS code that extracts field lineage information
    """
    
    def __init__(self):
        self.current_line = 0
        
    def parse(self, sas_code: str, expand_macros: bool = False, include_base: Optional[str] = None) -> SASProgram:
        """
        Parse SAS code end-to-end and return a SASProgram with field lineage.

        The source is tokenised into statements (semicolon-delimited, with
        comments and inline ``datalines``/``cards`` data removed) so that
        compact one-line steps such as ``data x; set y; run;`` and multi-
        statement lines are handled correctly across the whole file.

        When ``expand_macros`` is True, SAS ``%macro`` definitions are expanded
        first so steps generated by macros become plain code. Expansion is
        non-destructive (it never drops a step the source already contains).
        It is off by default because precise macro expansion of arbitrary real
        SAS needs a full macro engine; enable it for files that use the
        deterministic ``%do``/``%let``/``%if``/``%sysfunc`` subset.

        ``%include`` is only resolved when ``include_base`` is a directory.
        Included files are read from that directory (or below) only.

        The expander's diagnostics (topological orders used, dependency cycles
        it could not linearise, names left unresolved) are attached to the
        returned program as ``macro_report``.
        """
        program = SASProgram()
        program.macro_report = {}
        if expand_macros:
            sas_code, program.macro_report = preprocess_ex(sas_code, include_base=include_base)
        stmts = self._tokenize(sas_code)

        i = 0
        while i < len(stmts):
            text, line = stmts[i]
            self.current_line = line
            upper = text.upper()
            if not text:
                i += 1
                continue
            if upper.startswith('DATA '):
                data_step, i = self._parse_data_step(stmts, i)
                if data_step:
                    program.add_data_step(data_step)
                continue
            if upper.startswith('PROC '):
                proc_steps, i = self._parse_proc_step(stmts, i)
                for proc_step in proc_steps:
                    program.add_proc_step(proc_step)
                continue
            i += 1

        return program

    def _tokenize(self, sas_code: str) -> List[Tuple[str, int]]:
        """
        Split SAS source into logical statements ``(text, line)``.

        Comments are stripped, statements are delimited by ``;`` and inline
        ``datalines``/``cards`` (and ``*4`` variants) blocks are consumed as
        opaque data so their rows are never mistaken for code.
        """
        text = SASCodeCleaner.remove_comments(sas_code)
        stmts: List[Tuple[str, int]] = []
        cur = ""
        cur_line = 0
        cards = False

        for ln_idx, raw in enumerate(text.split("\n"), start=1):
            line = raw
            while line:
                if cards:
                    j = line.find(";")
                    if j == -1:
                        line = ""           # consume whole card-data line
                    else:
                        line = line[j + 1:]
                        cards = False
                    continue
                j = line.find(";")
                if j == -1:
                    if not cur_line:
                        cur_line = ln_idx
                    cur = (cur + " " + line).strip() if cur else line.strip()
                    break
                piece = line[:j].strip()
                if not cur_line:
                    cur_line = ln_idx
                cur = (cur + " " + piece).strip() if cur else piece
                stmt_text = cur.strip()
                stmt_line = cur_line
                cur, cur_line = "", 0
                if stmt_text:
                    stmts.append((stmt_text, stmt_line))
                    # A bare datalines/cards statement opens an inline data block.
                    if re.match(r"^(DATALINES4?|CARDS4?)\s*$", stmt_text.upper()):
                        cards = True
                line = line[j + 1:]
        if cur.strip():
            stmts.append((cur.strip(), cur_line or 1))
        return stmts
    
    def _parse_data_step(self, stmts, start_line: int) -> Tuple[Optional[DataStepNode], int]:
        """
        Parse a DATA step from a list of statements, returning the step and the
        index just after its terminator (``RUN;``/``QUIT;``).
        """
        text, line = stmts[start_line]
        # Everything after the DATA keyword is a dataset list: it may name
        # several outputs, carry a libref and dataset options on each, and end
        # with ``/`` step options.
        outputs = _split_dataset_refs(re.sub(r'^\s*DATA\b', '', text, count=1, flags=re.IGNORECASE))
        if not outputs:
            return None, start_line + 1

        output_table = outputs[0]
        data_step = DataStepNode(output_table=output_table, output_tables=outputs)

        i = start_line + 1
        while i < len(stmts):
            stmt, ln = stmts[i]
            upper = stmt.upper()
            # Terminators end the step (RUN; or QUIT;).
            if upper.startswith('RUN') or upper.startswith('QUIT'):
                i += 1
                break
            # A datalines/cards block is opaque data — nothing to extract.
            if re.match(r'^(DATALINES4?|CARDS4?)\b', upper):
                i += 1
                break

            keyword = upper.split(None, 1)[0] if upper.split() else ''
            if keyword in _INPUT_STATEMENTS:
                for t in _split_dataset_refs(stmt[len(keyword):]):
                    if t not in data_step.input_tables:
                        data_step.input_tables.append(t)
            elif upper.startswith('BY '):
                by_match = re.search(r'BY\s+([\w\s]+)', stmt, re.IGNORECASE)
                if by_match:
                    data_step.merge_keys.extend(k for k in by_match.group(1).split() if k.strip())
            else:
                assignment_match = re.search(r'(\w+)\s*=\s*(.+)', stmt)
                if assignment_match:
                    field_name = assignment_match.group(1)
                    expression = assignment_match.group(2).strip()
                    field_node = FieldNode(
                        name=field_name,
                        table=output_table,
                        operation=FieldOperationType.ASSIGNMENT,
                        expression=expression,
                        source_line=ln,
                    )
                    deps = self._extract_field_references(expression, data_step.input_tables)
                    for dep_name, dep_table in deps:
                        field_node.add_dependency(FieldNode(name=dep_name, table=dep_table))
                    data_step.add_field(field_node)
            i += 1

        unresolved = [t for t in data_step.output_tables + data_step.input_tables
                      if is_unresolved_table(t)]
        if unresolved:
            data_step.metadata['unresolved_tables'] = unresolved

        return data_step, i
    
    def _parse_proc_step(self, stmts, start_line: int) -> Tuple[List[ProcStepNode], int]:
        """
        Parse a PROC step, returning its step nodes and the index just after
        its terminator (``RUN;`` or ``QUIT;``).

        A ``PROC SQL`` block yields one node per ``CREATE TABLE`` /
        ``INSERT INTO`` statement, so each target keeps only its own sources;
        every other PROC yields a single node.
        """
        text, line = stmts[start_line]

        # Extract PROC name
        match = re.search(r'PROC\s+(\w+)', text, re.IGNORECASE)
        if not match:
            return [], start_line + 1

        proc_name = match.group(1).upper()
        inputs: List[str] = []
        outputs: List[str] = []
        sql_steps: List[ProcStepNode] = []

        # The PROC statement itself carries DATA=/OUT=, so scanning must start
        # on it and not on the statement after it.
        i = start_line
        while i < len(stmts):
            stmt, ln = stmts[i]
            upper = stmt.upper()
            if i > start_line and (upper.startswith('RUN') or upper.startswith('QUIT')):
                i += 1
                break

            for m in _DATA_OPT_RE.finditer(stmt):
                name = _normalize_table(m.group(1))
                if name and name not in inputs:
                    inputs.append(name)
            for rx in (_OUT_OPT_RE, _BASE_OPT_RE):
                for m in rx.finditer(stmt):
                    name = _normalize_table(m.group(1))
                    if name and name not in outputs:
                        outputs.append(name)

            if proc_name == 'SQL':
                # Each CREATE TABLE / INSERT INTO is its own derivation: they
                # must not share one input list, or every source of one
                # statement would look like a source of the others.
                targets = [_normalize_table(m.group(1)) for m in _SQL_CREATE_RE.finditer(stmt)]
                targets += [_normalize_table(m.group(1)) for m in _SQL_INSERT_RE.finditer(stmt)]
                sources = _sql_sources(stmt)
                if targets:
                    sql_steps.append(self._build_proc_step(proc_name, sources, targets))
                elif sources:
                    # A bare SELECT reads without writing; keep the reads.
                    for name in sources:
                        if name not in inputs:
                            inputs.append(name)

            i += 1

        steps = sql_steps
        if inputs or outputs or not steps:
            steps = [self._build_proc_step(proc_name, inputs, outputs)] + steps
        return steps, i

    @staticmethod
    def _build_proc_step(proc_name: str, inputs: List[str], outputs: List[str]) -> ProcStepNode:
        """Assemble one PROC step node from its resolved table names."""
        proc_step = ProcStepNode(proc_name=proc_name)
        proc_step.input_tables = list(inputs)
        proc_step.output_tables = list(outputs)
        proc_step.input_table = inputs[0] if inputs else None
        proc_step.output_table = outputs[0] if outputs else None
        unresolved = [t for t in outputs + inputs if is_unresolved_table(t)]
        if unresolved:
            proc_step.metadata['unresolved_tables'] = unresolved
        return proc_step
    
    def _extract_field_references(self, expression: str, source_tables: List[str]) -> List[Tuple[str, Optional[str]]]:
        """
        Extract field references from an expression
        Returns list of (field_name, table_name) tuples
        """
        references = []
        
        # Match field names (simple identifiers)
        # Look for table.field or just field
        qualified_refs = re.findall(r'(\w+)\.(\w+)', expression)
        for table, field in qualified_refs:
            references.append((field, table))
        
        # Find unqualified field references
        # Remove function names and operators
        cleaned_expr = re.sub(r'(\w+)\s*\(', '', expression)  # Remove function calls
        tokens = re.findall(r'\b([a-zA-Z_]\w*)\b', cleaned_expr)
        
        # Filter out SAS keywords and functions
        for token in tokens:
            if token.lower() not in SAS_KEYWORDS and not token.isdigit():
                # Try to infer table from source tables
                # Note: This defaults to first table which may be ambiguous
                table = source_tables[0] if source_tables else None
                if (token, table) not in references:
                    references.append((token, table))
        
        return references


class SASCodeCleaner:
    """
    Utility to clean and preprocess SAS code
    """
    
    @staticmethod
    def remove_comments(code: str) -> str:
        """Remove comments from SAS code"""
        # Remove /* */ style comments
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        # Remove * style comments (line comments)
        code = re.sub(r'^\s*\*[^;]*;', '', code, flags=re.MULTILINE)
        return code
    
    @staticmethod
    def normalize_whitespace(code: str) -> str:
        """Normalize whitespace in SAS code"""
        # Replace multiple spaces with single space
        code = re.sub(r'[ \t]+', ' ', code)
        return code
