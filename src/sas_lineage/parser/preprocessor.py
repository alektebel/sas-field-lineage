"""
A pragmatic %SAS macro preprocessor.

SAS macro language is large; this implements the deterministic subset that
real regulatory / clinical / analytics SAS actually uses, so that DATA / PROC
steps written *inside* macros are emitted as plain code and can be parsed for
lineage. It is deliberately conservative: any construct it does not understand
is passed through unchanged (never discarded, never crashed), so the caller
loses nothing.

Supported:
  %macro name(params=default, ...); ... %mend;        definitions
  %name(args)  and  %name;                            invocations
  %let name = text;  %put ...;                        variables / diagnostics
  &var  &&var  &var.member                            symbol resolution
  %if cond %then stmt %else stmt                      conditionals
  %do; %end;  %do i=a %to b %by c; %end;              loops
  %do %over(word-list); %end;                         list iteration
  %do %while(cond); %end;  %do %until(cond); %end;
  %include "file.sas";                                sandboxed, when include_base is set
  %eval %sysevalf %scan %index %substr %length %trim %left %upcase %downcase
  %cmpres %cats %catx %str %nrstr %bquote %quote %unquote
  %sysfunc(countw/count/length/find/sum/min/max/int/floor/ceil/round/abs/sqrt/...)
  %global / %local / %symdel                          declarations

Expansion runs in two phases so that *order of appearance in the file* stops
mattering for anything that can be resolved statically:

  1. A collect pass registers every ``%macro`` definition (including nested
     ones) and every top-level ``%let``, expanding nothing. Single-assignment
     ``%let``s are then evaluated in topological order of their dependencies,
     so ``%let a = &b._x;`` written *above* ``%let b = core;`` still yields
     ``core_x`` -- the literal real SAS produces, because SAS stores the
     unresolved text and resolves it at use time.
  2. The sequential pass expands the source. Because every definition is
     already registered, a macro invoked above its own ``%macro`` block
     resolves; because the pass is still sequential, a macro variable that is
     *re-assigned* keeps SAS's sequential semantics (topological order is
     unsound for those, so they are deliberately excluded from phase 1).

An unresolved ``&name`` keeps its own source text rather than collapsing to an
empty string, matching SAS (which warns and leaves the reference literal) and
keeping the pass non-destructive. Names that could not be resolved are
reported in ``MacroPreprocessor.unresolved``.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

_KEYWORDS = {
    "macro", "mend", "let", "put", "if", "then", "else",
    "do", "to", "by", "end", "while", "until",
}

_FUNCS = {
    "eval", "sysevalf", "sysfunc", "scan", "index", "substr", "length",
    "trim", "left", "right", "upcase", "downcase", "lowcase", "cmpres",
    "str", "nrstr", "bquote", "quote", "unquote", "nrbquote", "cats",
    "catx", "putn", "put", "subpad", "tranwrd", "verify", "repeat",
    "reverse", "symget", "indexc", "qtrim", "translate", "constant",
    "ceil", "floor", "sqrt", "max", "min", "compress", "dequote",
}

_ARITH_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}

_MAX_DEPTH = 40
_MAX_ITERS = 40000
_MAX_RESCAN = 20

# Scope key holding the names declared %local for the running macro. It is not
# a legal SAS macro-variable name, so it can never collide with a real symbol.
_LOCALS_KEY = "%locals"

_SYMREF_RE = re.compile(r"&+([A-Za-z_]\w*)")
_MACROREF_RE = re.compile(r"%([A-Za-z_]\w*)")

# Macro statements that declare or delete symbols: consumed up to the ``;``.
_DECL_STATEMENTS = {"global", "symdel", "syslput", "sysrput", "abort", "return", "goto"}

# SAS automatic macro variables. They are always "undefined" here because their
# value comes from the session, not the source, so they are reported apart from
# names that are genuinely missing -- otherwise a typo hides among them.
_AUTOMATIC_SYMBOLS = {
    "sysdate", "sysdate9", "systime", "sysday", "sysscp", "sysscpl", "sysuserid",
    "syslast", "sysrc", "syserr", "syserrortext", "syswarningtext", "sysver",
    "sysvlong", "sysvlong4", "sysjobid", "sysindex", "sysparm", "sysnobs",
    "sysfilrc", "syslibrc", "sysmacroname", "sysprocessname", "sysprocname",
    "sysstartdate", "sysstarttime", "sysenv", "syssite", "systcpiphostname",
    "sysdevic", "sysdsn", "syscc", "sysinfo", "sysncpu", "syshostname",
}

# ``call symput('name', 'literal')`` -- the one runtime assignment whose value
# is knowable without running the step.
_SYMPUT_LITERAL_RE = re.compile(
    r"""\bcall\s+symputx?\s*\(\s*(['"])(?P<name>[^'"]+)\1\s*,\s*(['"])(?P<value>[^'"]*)\3\s*\)""",
    re.IGNORECASE,
)
# Any ``call symput`` with a literal name, whatever the value expression is.
_SYMPUT_NAME_RE = re.compile(
    r"""\bcall\s+symputx?\s*\(\s*(['"])(?P<name>[^'"]+)\1\s*,""",
    re.IGNORECASE,
)


def _symbol_refs(text: str) -> List[str]:
    """Macro-variable names referenced as ``&name`` inside ``text``."""
    return [m.group(1).lower() for m in _SYMREF_RE.finditer(text)]


def _macro_refs(text: str) -> List[str]:
    """Macro names invoked as ``%name`` inside ``text`` (keywords excluded)."""
    out = []
    for m in _MACROREF_RE.finditer(text):
        name = m.group(1).lower()
        if name not in _KEYWORDS and name not in _FUNCS and name not in _DECL_STATEMENTS:
            out.append(name)
    return out


def _toposort(deps: Dict[str, Set[str]]) -> Tuple[List[str], List[str]]:
    """Kahn topological sort of ``{node: {dependencies}}``.

    Returns ``(order, cyclic)``: dependencies come before their dependants in
    ``order``, and ``cyclic`` lists the nodes that never became ready, i.e.
    the ones caught in a dependency cycle. A self-edge counts as a cycle --
    a macro that calls itself and a ``%let`` that appends to its own value are
    both things no order can linearise. Ties are broken by insertion order so
    the result is deterministic for a given source file."""
    nodes = list(deps)
    pending = {n: {d for d in deps[n] if d in deps} for n in nodes}
    dependants: Dict[str, List[str]] = {n: [] for n in nodes}
    for n in nodes:
        for d in pending[n]:
            dependants[d].append(n)
    ready = [n for n in nodes if not pending[n]]
    order: List[str] = []
    placed = set(ready)
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in dependants[n]:
            pending[m].discard(n)
            if not pending[m] and m not in placed:
                placed.add(m)
                ready.append(m)
    cyclic = [n for n in nodes if n not in placed]
    return order, cyclic


def _strip_macro_comments(text: str) -> str:
    text = re.sub(r"%\*.*?;", " ", text, flags=re.DOTALL)          # %* ... ;
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)        # /* ... */
    return text


def _balanced(text: str, open_idx: int) -> Tuple[str, int]:
    depth = 0
    for j in range(open_idx, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:j], j + 1
    return "", len(text)


def _find_top(text: str, start: int, targets: List[str]) -> Tuple[int, str]:
    """Find the first target macro-keyword, skipping function-call parens."""
    i = start
    while i < len(text):
        if text[i] == "%":
            m = re.match(r"%([A-Za-z_]\w*)", text[i:])
            if m:
                kw = m.group(1).lower()
                j = i + m.end()
                while j < len(text) and text[j] == " ":
                    j += 1
                if kw in _FUNCS and j < len(text) and text[j] == "(":
                    _, j = _balanced(text, j)
                    i = j
                    continue
                if kw in targets:
                    return i, kw
                i = j
                continue
        i += 1
    return -1, ""


def _matching_mend(text: str, start: int) -> int:
    depth = 0
    i = start
    while i < len(text):
        m = re.search(r"%\s*(macro|mend)\b", text[i:], re.IGNORECASE)
        if not m:
            return len(text)
        kw = m.group(1).lower()
        j = i + m.start()
        if kw == "macro":
            depth += 1
        else:
            depth -= 1
            if depth <= 0:
                semi = text.find(";", j)
                return len(text) if semi == -1 else semi + 1
            i = j + len("mend")
        i = j + len(kw)
    return len(text)


def _parse_params(spec: str) -> List[Tuple[str, str]]:
    if not spec.strip():
        return []
    out = []
    for part in _split_commas(spec):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            name, _, default = part.partition("=")
            out.append((name.strip().lower(), default.strip()))
        else:
            out.append((part.strip().lower(), ""))
    return out


def _split_commas(text: str) -> List[str]:
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return parts


def _numeric(v) -> Optional[float]:
    s = str(v).strip().replace(",", "")
    if re.fullmatch(r"-?\d+", s):
        return float(int(s))
    if re.fullmatch(r"-?\d+\.?\d*(?:[eE][+-]?\d+)?", s):
        return float(s)
    return None


def _arith(expr: str):
    """Evaluate a numeric string expression; raises on non-numeric."""
    tree = ast.parse(expr.strip(), mode="eval")

    def walk(n):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.BinOp):
            try:
                return _ARITH_OPS[type(n.op)](walk(n.left), walk(n.right))
            except KeyError:
                raise ValueError("op")
        if isinstance(n, ast.UnaryOp):
            try:
                return _ARITH_OPS[type(n.op)](walk(n.operand))
            except KeyError:
                raise ValueError("op")
        raise ValueError("node")

    return walk(tree.body)


def _fmt_num(x) -> str:
    f = float(x)
    return str(int(f)) if f == int(f) else str(f)


def _side(v: str):
    try:
        val = _arith(v)
        if isinstance(val, (int, float)):
            return val
    except Exception:
        pass
    return v.strip()


def _op(a, o, b):
    a, b = _side(str(a)), _side(str(b))
    au, bu = str(a).upper(), str(b).upper()
    if o in ("=", "eq", "eq:"): return au == bu
    if o in ("^=", "ne", "<>", "!="): return au != bu
    if o in (">", "gt"): return a > b if isinstance(a, (int, float)) and isinstance(b, (int, float)) else au > bu
    if o in ("<", "lt"): return a < b if isinstance(a, (int, float)) and isinstance(b, (int, float)) else au < bu
    if o in (">=", "ge", ">="): return a >= b if isinstance(a, (int, float)) and isinstance(b, (int, float)) else au >= bu
    if o in ("<=", "le", "<="): return a <= b if isinstance(a, (int, float)) and isinstance(b, (int, float)) else au <= bu
    if o == "+": return a + b if isinstance(a, (int, float)) and isinstance(b, (int, float)) else str(a) + str(b)
    if o == "-": return a - b if isinstance(a, (int, float)) and isinstance(b, (int, float)) else a
    if o == "*": return a * b if isinstance(a, (int, float)) and isinstance(b, (int, float)) else 0
    if o == "/": return a / b if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b != 0 else 0
    return str(a)


_COMPARE_RE = re.compile(r"^\s*(.+?)\s*(<=|>=|=|EQ|NE|GT|LT|GE|LE|\^=|<>|<|>)\s*(.*?)\s*$", re.I | re.S)


def _eval_cond(expr: str, resolve) -> bool:
    expr = resolve(expr).strip()
    expr = re.sub(r"\b(AND)\b", " and ", expr, flags=re.I)
    expr = re.sub(r"\b(NOT)\b", " not ", expr, flags=re.I)
    expr = re.sub(r"\b(OR)\b", " or ", expr, flags=re.I)

    def atom(v: str) -> bool:
        v = v.strip()
        if v.startswith("(") and v.endswith(")"):
            return _eval_cond(v[1:-1], resolve)
        if v.upper() in ("TRUE", "YES"):
            return True
        if v.upper() in ("FALSE", "NO", "0", ""):
            return False
        try:
            return _arith(v) != 0
        except Exception:
            return v.upper() not in ("", "0", "false", "no")

    # top-level comparison
    m = _COMPARE_RE.match(expr)
    if m:
        return _op(m.group(1), m.group(2).lower(), m.group(3))

    for word in (" and ", " or "):
        if word in expr:
            parts = expr.split(word)
            vals = [atom(p) for p in parts if p.strip()]
            return all(vals) if word == " and " else any(vals)

    if " not " in expr:
        return not atom(expr.split(" not ")[-1])
    return atom(expr)


class MacroPreprocessor:
    def __init__(self, include_base: Optional[str] = None):
        self.macros: Dict[str, Dict] = {}
        self.symbols: Dict[str, str] = {}
        self.include_base = include_base
        self._include_seen: set = set()
        # Diagnostics filled in by the collect / topological phase.
        self.symbol_order: List[str] = []
        self.symbol_cycles: List[str] = []
        self.macro_order: List[str] = []
        self.macro_cycles: List[str] = []
        self.unresolved: Set[str] = set()
        self.unresolved_macros: Set[str] = set()
        self.automatic: Set[str] = set()
        self.runtime_symbols: Set[str] = set()

    # ------------------------------------------------------------------ #
    def preprocess(self, code: str, include_base: Optional[str] = None) -> str:
        self.include_base = include_base or self.include_base
        code = _strip_macro_comments(code)
        lets = self._scan_definitions(code)
        self._order_macros()
        self._resolve_lets_topologically(lets + self._scan_symput(code))
        return self._expand(code, self.symbols, depth=0)

    def report(self) -> Dict[str, Any]:
        """Diagnostics for the last ``preprocess`` call."""
        return {
            "symbol_order": list(self.symbol_order),
            "symbol_cycles": list(self.symbol_cycles),
            "macro_order": list(self.macro_order),
            "macro_cycles": list(self.macro_cycles),
            "unresolved_symbols": sorted(self.unresolved),
            "unresolved_macros": sorted(self.unresolved_macros),
            "automatic_symbols": sorted(self.automatic),
            "runtime_symbols": sorted(self.runtime_symbols),
        }

    # ---- phase 1: collect definitions, then order them ------------------ #
    def _scan_definitions(self, text: str, collect_lets: bool = True) -> List[Tuple[str, str]]:
        """Register every ``%macro`` definition without expanding anything.

        Returns the ``(name, raw_value)`` of the ``%let`` statements written at
        the top level of ``text``. Registering definitions up-front is what
        makes a macro invoked *above* its own ``%macro`` block resolve, instead
        of expanding to nothing and taking the whole file down the
        "expansion lost every step" fallback path.

        ``%let``s inside a macro body are not collected: their value depends on
        the invocation, so only the sequential pass can evaluate them."""
        lets: List[Tuple[str, str]] = []
        i, n = 0, len(text)
        while i < n:
            if text[i] != "%":
                i += 1
                continue
            m = re.match(r"%\s*([A-Za-z_]\w*)", text[i:])
            if not m:
                i += 1
                continue
            kw = m.group(1).lower()
            j = i + m.end()
            if kw == "macro":
                end = _matching_mend(text, i)
                self._register_macro(text[i:end])
                i = end if end > i else i + m.end()
                continue
            if kw == "let":
                sem = text.find(";", j)
                if sem == -1:
                    break
                name, eq, value = text[j:sem].partition("=")
                name = name.strip().lower()
                if collect_lets and eq and re.fullmatch(r"[A-Za-z_]\w*", name):
                    lets.append((name, value.strip()))
                i = sem + 1
                continue
            i = j
        return lets

    def _scan_symput(self, text: str) -> List[Tuple[str, str]]:
        """Collect ``call symput('name', 'literal')`` assignments.

        SAS only creates these when the DATA step runs, and this pass does not
        run DATA steps -- so without this the symbol is simply never defined
        and every table name built from it stays unresolved. Harvesting is
        limited to a **literal** value, the only case where the result does not
        depend on the data. A non-literal value is recorded in
        ``runtime_symbols`` so the gap is named rather than guessed at.
        """
        literal = {m.group("name").lower() for m in _SYMPUT_LITERAL_RE.finditer(text)}
        for m in _SYMPUT_NAME_RE.finditer(text):
            name = m.group("name").lower()
            if name not in literal:
                self.runtime_symbols.add(name)
        return [(m.group("name").lower(), m.group("value"))
                for m in _SYMPUT_LITERAL_RE.finditer(text)]

    def _register_macro(self, block: str) -> None:
        """Store one ``%macro ... %mend`` block, plus any macro nested in it."""
        head = re.match(r"%\s*macro\s*", block, re.IGNORECASE)
        if not head:
            return
        spec_end = block.find(";")
        if spec_end == -1:
            return
        spec = block[head.end():spec_end].strip()
        hm = re.match(r"([A-Za-z_]\w*)\s*(?:\((.*)\))?$", spec, flags=re.S)
        if not hm:
            return
        body = block[spec_end + 1:]
        mend_at = body.lower().rfind("%mend")
        if mend_at != -1:
            body = body[:mend_at]
        self.macros[hm.group(1).lower()] = {
            "params": _parse_params(hm.group(2) or ""),
            "body": body,
        }
        self._scan_definitions(body, collect_lets=False)

    def _order_macros(self) -> None:
        """Topologically order the registered macros: callees before callers.

        Expansion itself is lazy, so this order is not what drives it; what it
        buys is a name for the macros the order *cannot* linearise, i.e. the
        recursive ones, which are exactly the ones ``_MAX_DEPTH`` can truncate
        silently."""
        deps = {
            name: {c for c in _macro_refs(spec["body"]) if c in self.macros}
            for name, spec in self.macros.items()
        }
        self.macro_order, self.macro_cycles = _toposort(deps)

    def _resolve_lets_topologically(self, lets: List[Tuple[str, str]]) -> None:
        """Pre-evaluate the single-assignment ``%let``s in dependency order.

        The input is the top-level ``%let``s plus the literal
        ``call symput`` assignments, which are definitions of the same kind.

        A macro variable assigned more than once is sequential state, and a
        topological order would silently pick the wrong assignment, so those
        are left entirely to the sequential pass. A name assigned exactly once
        is a definition: evaluating it after its dependencies reproduces what
        SAS gets by storing the unresolved text and resolving it at use time.

        The sequential pass re-executes the same ``%let``s afterwards; by then
        every dependency is bound, so it recomputes the same value. Pre-
        evaluation only changes what happens *before* the source-order
        assignment is reached."""
        counts: Dict[str, int] = {}
        for name, _ in lets:
            counts[name] = counts.get(name, 0) + 1
        single = {name: value for name, value in lets if counts[name] == 1}
        deps = {
            name: {d for d in _symbol_refs(value) if d in single}
            for name, value in single.items()
        }
        self.symbol_order, self.symbol_cycles = _toposort(deps)
        for name in self.symbol_order:
            self.symbols[name] = self._expand(single[name], self.symbols, depth=1)

    # ---- symbol resolution ------------------------------------------- #
    def _symval(self, name: str, scope: Dict[str, str]) -> Optional[str]:
        """Value bound to ``name``, or ``None`` when the symbol is unknown.

        ``None`` is distinct from ``""``: an unbound reference must keep its
        source text so a later rescan (or a later ``%let``) can still resolve
        it, while a genuinely empty value must expand to nothing."""
        key = name.lower()
        val = scope.get(key)
        if val is None and scope is not self.symbols:
            val = self.symbols.get(key)
        return val

    def _resolve_once(self, text: str, scope: Dict[str, str]) -> Tuple[str, bool]:
        """One SAS symbol-resolution pass. Returns ``(text, changed)``.

        ``&&`` collapses to a single ``&`` that survives into the next pass,
        which is what makes the ``&&prefix&i`` indirection idiom name the
        variable ``prefix<i>`` instead of concatenating two lookups."""
        out: List[str] = []
        changed = False
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if ch != "&":
                out.append(ch)
                i += 1
                continue
            if i + 1 < n and text[i + 1] == "&":
                out.append("&")
                i += 2
                changed = True
                continue
            m = re.match(r"([A-Za-z_]\w*)", text[i + 1:])
            if not m:
                out.append(ch)
                i += 1
                continue
            name = m.group(1)
            j = i + 1 + m.end()
            if j < n and text[j] == ".":
                j += 1  # the name-delimiter dot is consumed, not emitted
            val = self._symval(name, scope)
            if val is None:
                key = name.lower()
                (self.automatic if key in _AUTOMATIC_SYMBOLS else self.unresolved).add(key)
                out.append(text[i:j])   # leave the reference literal, SAS-style
            else:
                out.append(val)
                changed = True
            i = j
        return "".join(out), changed

    def _resolve(self, text: str, scope: Dict[str, str]) -> str:
        """Resolve ``&`` references, rescanning until the text stops changing."""
        for _ in range(_MAX_RESCAN):
            new, changed = self._resolve_once(text, scope)
            if not changed or new == text:
                return new
            text = new
        return text

    # ---- main expander ------------------------------------------------- #
    def _expand(self, text: str, scope: Dict[str, str], depth: int) -> str:
        if depth > _MAX_DEPTH:
            return text
        out = []
        i = 0
        iters = 0
        while i < len(text):
            iters += 1
            if iters > _MAX_ITERS:
                return "".join(out) + text[i:]
            ch = text[i]
            if ch == "%":
                m = re.match(r"%([A-Za-z_]\w*)", text[i:])
                if not m:
                    out.append(ch)
                    i += 1
                    continue
                name = m.group(1).lower()
                j = i + m.end()
                while j < len(text) and text[j] == " ":
                    j += 1
                if name == "macro":
                    if text.find(";", j) == -1:
                        out.append(text[i:])
                        break
                    def_end = _matching_mend(text, i)
                    # Re-registering here (the collect pass already did it)
                    # keeps SAS's sequential semantics for a redefinition:
                    # invocations below this point see the newer body.
                    self._register_macro(text[i:def_end])
                    i = def_end
                    continue
                if name == "mend":
                    sem = text.find(";", i)
                    i = len(text) if sem == -1 else sem + 1
                    continue
                if name == "let":
                    sem = text.find(";", j)
                    if sem == -1:
                        out.append(text[i:])
                        break
                    stmt = text[j:sem]
                    vname, eq, rest = stmt.partition("=")
                    vname = vname.strip().lower()
                    if vname and eq:
                        value = self._expand(rest.strip(), scope, depth + 1)
                        # %let writes the global table unless the name was
                        # declared %local (or is a parameter of the running
                        # macro), which is what keeps two invocations of the
                        # same macro from overwriting each other's names.
                        if vname in scope.get(_LOCALS_KEY, ()):
                            scope[vname] = value
                        else:
                            self.symbols[vname] = value
                    i = sem + 1
                    continue
                if name == "local":
                    sem = text.find(";", j)
                    if sem == -1:
                        i = len(text)
                        continue
                    declared = scope.setdefault(_LOCALS_KEY, set())
                    for nm in re.findall(r"[A-Za-z_]\w*", self._resolve(text[j:sem], scope)):
                        declared.add(nm.lower())
                        scope.setdefault(nm.lower(), "")
                    i = sem + 1
                    continue
                if name in _DECL_STATEMENTS:
                    sem = text.find(";", j)
                    i = len(text) if sem == -1 else sem + 1
                    continue
                if name == "include":
                    sem = text.find(";", j)
                    if sem == -1:
                        out.append(text[i:])
                        break
                    out.append(self._expand_include(text[j:sem], scope, depth))
                    i = sem + 1
                    continue
                if name == "put":
                    sem = text.find(";", j)
                    i = len(text) if sem == -1 else sem + 1
                    continue
                if name == "if":
                    txt, ni = self._expand_if(text, j, scope, depth)
                    out.append(txt)
                    i = ni
                    continue
                if name == "do":
                    txt, ni = self._expand_do(text, j, scope, depth)
                    out.append(txt)
                    i = ni
                    continue
                if name == "end":
                    sem = text.find(";", j)
                    i = len(text) if sem == -1 else sem + 1
                    continue
                if name in ("to", "by", "then", "else", "while", "until"):
                    out.append(text[i:])
                    break
                if j < len(text) and text[j] == "(":
                    arg_text, after = _balanced(text, j)
                    if name in _FUNCS:
                        out.append(self._call_func(name, arg_text, scope, depth))
                    else:
                        out.append(self._invoke(name, arg_text, scope, depth, text[i:after]))
                    i = after
                    continue
                if name in _FUNCS:
                    out.append(self._call_func(name, "", scope, depth))
                    i = j
                    continue
                out.append(self._invoke(name, "", scope, depth, text[i:i + m.end()]))
                i = j
                continue
            if ch == "&":
                # Resolve the whole reference run at once (``&&tab&i`` is one
                # run, not two lookups) and let _resolve rescan it.
                run = re.match(r"[&\w.]+", text[i:]).group(0)
                out.append(self._resolve(run, scope))
                i += len(run)
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    # ---- %include ------------------------------------------------------- #
    def _expand_include(self, stmt: str, scope, depth: int) -> str:
        text = self._resolve(stmt, scope).strip()
        chunks = []
        for m in re.finditer(r"\"([^\"]+)\"|'([^']+)'|([^\s]+)", text):
            path = (m.group(1) or m.group(2) or m.group(3) or "").strip()
            if path:
                chunks.append(self._include_text(path, scope, depth))
        return "".join(chunks)

    def _include_text(self, path: str, scope, depth: int) -> str:
        if not self.include_base or depth >= _MAX_DEPTH:
            return ""
        try:
            base = Path(self.include_base).resolve()
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = base / candidate
            resolved = candidate.resolve()
            if not resolved.is_relative_to(base) or str(resolved) in self._include_seen:
                return ""
            self._include_seen.add(str(resolved))
            body = resolved.read_text(errors="replace")
        except Exception:
            return ""
        body = _strip_macro_comments(body)
        # Collect the included file's definitions first, for the same reason
        # the top-level pass does: order of appearance must not decide whether
        # a macro resolves.
        lets = self._scan_definitions(body)
        self._order_macros()
        self._resolve_lets_topologically(lets)
        return self._expand(body, scope, depth + 1)

    # ---- control flow --------------------------------------------------- #
    def _cond(self, expr: str, scope) -> bool:
        try:
            return _eval_cond(expr, lambda s: self._resolve(s, scope))
        except Exception:
            return False

    def _branch_end(self, text, start) -> int:
        """Index where one branch (a statement or a ``%do``/``%if`` block) ends.

        Stops before a top-level ``%else`` or ``%end``; a ``;`` closes a branch
        only when no ``%do`` block is open."""
        i = start
        n = len(text)
        paren = 0
        bdepth = 0
        while i < n:
            ch = text[i]
            if ch == "(":
                paren += 1
            elif ch == ")":
                paren -= 1
            if ch == "%":
                m = re.match(r"%([A-Za-z_]\w*)", text[i:])
                if m:
                    kw = m.group(1).lower()
                    after = i + m.end()
                    if kw == "do":
                        bdepth += 1
                        i = after
                        continue
                    if kw == "end":
                        if bdepth > 0:
                            bdepth -= 1
                            i = after
                            continue
                        return i
                    if kw == "else":
                        return i
                    if kw == "if":
                        ti, tn = _find_top(text, after, ["then"])
                        if tn == "then":
                            ek, en = _find_top(text, ti + len("%then"), ["else", "end"])
                            i = ek if en == "else" else ek
                            continue
                        i = after
                        continue
                    if kw == "macro":
                        endi = _matching_mend(text, i)
                        i = endi
                        continue
                    if kw in _FUNCS and after < n and text[after] == "(":
                        _, after = _balanced(text, after)
                        i = after
                        continue
                    i = after
                    continue
            if ch == ";" and paren <= 0 and bdepth <= 0:
                return i + 1
            i += 1
        return n

    def _expand_if(self, text, j, scope, depth):
        """Return (expanded_then_or_else, next_index)."""
        then_kw, then_name = _find_top(text, j, ["then"])
        if then_name != "then":
            sem = text.find(";", j)
            return "", (len(text) if sem == -1 else sem + 1)
        cond = text[j:then_kw].strip()
        bt = then_kw + len("%then")
        br1_end = self._branch_end(text, bt)
        then_text = text[bt:br1_end]

        k = br1_end
        while k < len(text) and text[k] in " \t\r\n":
            k += 1
        m = re.match(r"%else\b", text[k:], re.I)
        if m:
            else_start = k + m.end()
            br2_end = self._branch_end(text, else_start)
            else_text = text[else_start:br2_end]
            next_index = br2_end
        else:
            else_text = ""
            next_index = br1_end

        chosen = then_text if self._cond(cond, scope) else else_text
        return self._expand(chosen, scope, depth + 1), next_index

    def _expand_do(self, text, j, scope, depth):
        """Return (expanded_loop, next_index)."""
        sem = text.find(";", j)
        if sem == -1:
            return "", len(text)
        header = text[j:sem].strip()
        end_idx = self._find_block_end(text, sem)
        body = text[sem + 1:end_idx]
        if not header:
            return self._expand(body, scope, depth + 1), end_idx

        up = header.upper()
        if up.startswith("%WHILE"):
            cond = header[len("%while"):].strip().strip("(").rstrip(")")
            guard = 0
            parts = []
            while self._cond(cond, scope) and guard < 2000:
                parts.append(self._expand(body, scope, depth + 1))
                guard += 1
            return "".join(parts), end_idx
        if up.startswith("%UNTIL"):
            cond = header[len("%until"):].strip().strip("(").rstrip(")")
            guard = 0
            parts = []
            while guard < 2000:
                parts.append(self._expand(body, scope, depth + 1))
                guard += 1
                if self._cond(cond, scope):
                    break
            return "".join(parts), end_idx
        # %do %over (word list);  /  %do name %over word-list;
        mo = re.match(r"^(?:(\w+)\s+)?%OVER\b\s*(.+)$", header, flags=re.I)
        if mo:
            var = (mo.group(1) or "i").lower()
            lst = mo.group(2).strip()
            if lst.startswith("(") and lst.endswith(")"):
                lst = lst[1:-1].strip()
            items = self._expand(lst, scope, depth + 1).split()
            parts = []
            for w in items:
                scope[var] = w
                parts.append(self._expand(body, scope, depth + 1))
            return "".join(parts), end_idx
        # %do i = a %to b [%by c];
        m = re.search(r"%?([A-Za-z_]\w*)\s*=\s*(.+?)\s*%TO\s+(.+?)(?:\s*%BY\s+(.+?))?\s*$",
                      header, flags=re.I | re.S)
        if not m:
            return self._expand(body, scope, depth + 1), end_idx
        var = m.group(1).strip().lower()
        start_val = _numeric(self._expand(m.group(2), scope, depth + 1))
        end_val = _numeric(self._expand(m.group(3), scope, depth + 1))
        by = _numeric(self._expand(m.group(4).strip(), scope, depth + 1)) if m.group(4) else 1
        if start_val is None or end_val is None or by is None:
            return self._expand(body, scope, depth + 1), end_idx
        by = by if by != 0 else 1
        parts = []
        cur = start_val
        guard = 0
        while (by > 0 and cur <= end_val) or (by < 0 and cur >= end_val):
            scope[var] = _fmt_num(cur)
            parts.append(self._expand(body, scope, depth + 1))
            cur += by
            guard += 1
            if guard > 2000:
                break
        return "".join(parts), end_idx

    def _find_block_end(self, text, start) -> int:
        """Index just after the ``%end`` that closes a ``%do`` block.

        Only ``%do``/``%end`` are counted; ``%if`` is delimited by
        ``%then``/``%else`` and must not contribute depth."""
        depth = 0
        i = start
        while i < len(text):
            m = re.search(r"%\s*(do|end)\b", text[i:], re.IGNORECASE)
            if not m:
                return len(text)
            kw = m.group(1).lower()
            j = i + m.start() + m.end()
            if kw == "do":
                depth += 1
            elif kw == "end":
                depth -= 1
                if depth <= 0:
                    sem = text.find(";", j)
                    return len(text) if sem == -1 else sem + 1
            i = j
        return len(text)

    # ---- macro invocation / functions ------------------------------------ #
    def _invoke(self, name: str, args_text: str, scope, depth, raw: str = "") -> str:
        if name not in self.macros:
            # Every definition in the file was registered by the collect pass,
            # so an unknown name is genuinely external (autocall library, a
            # %sysfunc alias). Keep its source text rather than deleting code.
            self.unresolved_macros.add(name)
            return raw
        macro = self.macros[name]
        args_list = _split_commas(args_text) if args_text else []
        bind: Dict[str, str] = {}
        positional: List[str] = []
        for a in args_list:
            a = a.strip()
            if not a:
                continue
            if "=" in a:
                k, _, v = a.partition("=")
                bind[k.strip().lower()] = self._expand(v.strip(), scope, depth + 1)
            else:
                positional.append(a)
        local = dict(scope)
        # A macro gets a fresh local scope: its parameters are local in SAS,
        # and %local declarations in its body must not leak to the caller.
        declared = {p for p, _ in macro["params"]}
        local[_LOCALS_KEY] = set(declared)
        for i, (pname, default) in enumerate(macro["params"]):
            local[pname] = ""
            if pname in bind:
                local[pname] = bind[pname]
            elif i < len(positional):
                local[pname] = self._expand(positional[i].strip(), scope, depth + 1)
            elif default:
                local[pname] = self._expand(default, scope, depth + 1)
        return self._expand(macro["body"], local, depth + 1)

    def _call_func(self, name: str, arg_text: str, scope, depth) -> str:
        try:
            if name == "nrstr":
                # %nrstr is the one that masks & and %: its argument must not
                # be resolved, which is how a literal ``&`` survives.
                return arg_text
            if name in ("str", "bquote", "quote", "nrbquote", "dequote"):
                # These mask special characters but still resolve references,
                # so ``%let t = %str(&lib..tab);`` yields a real table name.
                return self._expand(arg_text, scope, depth + 1)
            if name in ("unquote", "unquote3"):
                return self._resolve(arg_text, scope)
            if name in ("eval", "sysevalf"):
                v = self._resolve(arg_text, scope)
                try:
                    return _fmt_num(_arith(v))
                except Exception:
                    return v.strip()
            if name in ("length", "lengthn"):
                return str(len(self._resolve(arg_text, scope)))
            if name in ("trim", "left", "right", "qtrim"):
                return self._resolve(arg_text, scope).strip()
            if name == "upcase":
                return self._resolve(arg_text, scope).upper()
            if name in ("lowcase", "downcase"):
                return self._resolve(arg_text, scope).lower()
            if name == "cmpres":
                return " ".join(self._resolve(arg_text, scope).split())
            if name == "cats":
                return "".join(self._resolve(a, scope).strip() for a in _split_commas(arg_text))
            if name == "catx":
                parts = _split_commas(arg_text)
                sep = self._resolve(parts[0], scope) if parts else ""
                return sep.join(self._resolve(a, scope).strip() for a in parts[1:])
            if name in ("substr", "subpad"):
                parts = _split_commas(arg_text)
                v = self._resolve(parts[0], scope)
                if len(parts) < 2:
                    return v
                try:
                    start = int(float(self._resolve(parts[1], scope) or 0))
                except Exception:
                    start = 1
                if len(parts) > 2:
                    try:
                        ln = int(float(self._resolve(parts[2], scope) or 0))
                    except Exception:
                        ln = len(v)
                    return v[start - 1:start - 1 + ln]
                return v[start - 1:]
            if name == "scan":
                parts = _split_commas(arg_text)
                v = self._resolve(parts[0], scope) if parts else ""
                try:
                    idx = int(float(self._resolve(parts[1], scope) or 1))
                except Exception:
                    idx = 1
                delims = None
                if len(parts) > 2:
                    delims = self._resolve(parts[2], scope) or " "
                toks = re.split(f"[{re.escape(delims or ' ')}]+", v) if v else []
                return toks[idx - 1] if 1 <= idx <= len(toks) else ""
            if name == "index":
                parts = _split_commas(arg_text)
                v = self._resolve(parts[0], scope)
                needle = self._resolve(parts[1], scope)
                return str(v.find(needle) + 1)
            if name == "indexc":
                parts = _split_commas(arg_text)
                v = self._resolve(parts[0], scope)
                chars = self._resolve(parts[1], scope) if len(parts) > 1 else ""
                for i, c in enumerate(v):
                    if c in chars:
                        return str(i + 1)
                return "0"
            if name == "symget":
                parts = _split_commas(arg_text)
                key = self._resolve(parts[0], scope).strip().lower()
                return self.symbols.get(key, "")
            if name == "sysfunc":
                return self._sysfunc(arg_text, scope, depth)
            if name in ("put", "putn"):
                parts = _split_commas(arg_text)
                return self._resolve(parts[0], scope) if parts else ""
            if name in ("max", "min"):
                vals = [_numeric(self._resolve(a, scope)) for a in _split_commas(arg_text)]
                vals = [v for v in vals if v is not None]
                return _fmt_num(max(vals)) if vals and name == "max" else (_fmt_num(min(vals)) if vals else "")
            if name == "repeat":
                parts = _split_commas(arg_text)
                v = self._resolve(parts[0], scope)
                try:
                    n = int(float(self._resolve(parts[1], scope) or 0))
                except Exception:
                    n = 0
                return v * (n + 1)
            if name == "translate":
                parts = _split_commas(arg_text)
                if len(parts) == 3:
                    v = self._resolve(parts[0], scope)
                    to = self._resolve(parts[1], scope)
                    frm = self._resolve(parts[2], scope)
                    return "".join(dict(zip(frm, to)).get(c, c) for c in v)
                return self._resolve(arg_text, scope)
            if name == "compress":
                return "".join(self._resolve(arg_text, scope).split())
            if name in ("constant", "sqrt", "ceil", "floor"):
                v = self._resolve(arg_text, scope)
                try:
                    return _fmt_num(_arith(v))
                except Exception:
                    return v
            return self._resolve(arg_text, scope)
        except Exception:
            return ""

    def _sysfunc(self, arg_text: str, scope, depth) -> str:
        text = arg_text.strip()
        m = re.match(r"^([A-Za-z_]\w*)\s*\((.*)\)$", text, flags=re.S)
        if not m:
            return self._resolve(arg_text, scope)
        fn = m.group(1).lower()
        args = [self._resolve(a, scope).strip() for a in _split_commas(m.group(2))]
        if fn == "countw":
            v = args[0] if args else ""
            delims = args[1] if len(args) > 1 and args[1] else " "
            toks = [t for t in re.split("[" + re.escape(delims) + "]+", v) if t]
            return str(len(toks))
        if fn == "count":
            return str(args[0].count(args[1])) if len(args) >= 2 else "0"
        if fn in ("length", "lengthn", "trimn", "datalength"):
            return str(len(args[0]) if args else 0)
        if fn == "find":
            return str(args[0].find(args[1]) + 1) if len(args) >= 2 else "0"
        if fn == "reverse":
            return args[0][::-1] if args else ""
        if fn == "compress":
            return "".join(args[0].split()) if args else ""
        nums = [_numeric(a) for a in args]
        if fn == "sum":
            vals = [v for v in nums if v is not None]
            return _fmt_num(sum(vals)) if vals else "0"
        if fn == "min":
            vals = [v for v in nums if v is not None]
            return _fmt_num(min(vals)) if vals else (args[0] if args else "")
        if fn == "max":
            vals = [v for v in nums if v is not None]
            return _fmt_num(max(vals)) if vals else (args[0] if args else "")
        if nums and nums[0] is not None:
            if fn in ("int", "floor"):
                return _fmt_num(math.floor(nums[0]))
            if fn == "ceil":
                return _fmt_num(math.ceil(nums[0]))
            if fn == "abs":
                return _fmt_num(abs(nums[0]))
            if fn == "sqrt":
                return _fmt_num(math.sqrt(nums[0])) if nums[0] >= 0 else ""
            if fn == "round":
                nd = int(nums[1]) if len(nums) > 1 and nums[1] is not None else 0
                return _fmt_num(round(nums[0], nd))
        if fn in ("put", "putn", "input", "n"):
            return args[0] if args else ""
        return self._resolve(arg_text, scope)

    def expand(self, code: str) -> str:
        return self.preprocess(code)


def _has_steps(text: str) -> bool:
    return re.search(r"(?m)^\s*(?:data|proc)\s+\w", text) is not None


def preprocess(code: str, include_base: Optional[str] = None) -> str:
    """Expand SAS ``%macro`` code for lineage parsing.

    The expander is explicitly non-destructive: if expansion would lose
    *every* DATA / PROC step the source already has (an unbalanced macro, or a
    construct the deterministic subset cannot generate), the original source is
    returned untouched so the parser still reads the file end-to-end. When it
    does produce steps (e.g. ``%do`` loops, ``%if/%else`` branches, invoked
    macros) the expansion is used even if it changes the step count.

    ``%include`` is only resolved when ``include_base`` is supplied, and only
    for files that stay under that directory."""
    return preprocess_ex(code, include_base)[0]


def preprocess_ex(code: str, include_base: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """``preprocess`` plus the expander's diagnostics.

    The second element carries the topological orders that were used, the
    dependency cycles that could not be linearised, and the names that stayed
    unresolved -- which is what lets a caller tell a table name it *knows* from
    one it merely copied through."""
    raw = code
    pre = MacroPreprocessor(include_base)
    try:
        out = pre.preprocess(code)
    except Exception as exc:  # never let a macro edge case kill the parse
        return raw, {"error": f"{type(exc).__name__}: {exc}"}
    report = pre.report()
    if _has_steps(raw) and not _has_steps(out):
        report["fallback"] = "expansion produced no step; source returned unexpanded"
        return raw, report
    return out, report
