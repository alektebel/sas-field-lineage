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
"""

from __future__ import annotations

import ast
import math
import operator
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

    # ------------------------------------------------------------------ #
    def preprocess(self, code: str, include_base: Optional[str] = None) -> str:
        self.include_base = include_base or self.include_base
        code = _strip_macro_comments(code)
        return self._expand(code, self.symbols, depth=0)

    # ---- symbol resolution ------------------------------------------- #
    def _read_symref(self, text: str, amp_idx: int, scope: Dict[str, str]):
        """Read a symbol ref at ``&``.

        Returns ``(kind, text, next_index)`` where kind is ``"sym"`` (a name to
        resolve) or ``"val"`` (already-resolved text from a ``&&`` chain). A
        single trailing ``.`` is a SAS name delimiter and is consumed, so
        ``&prefix._&i`` resolves like ``prefix_&i``."""
        j = amp_idx + 1
        indirection = 0
        while j < len(text) and text[j] == "&":
            indirection += 1
            j += 1
        m = re.match(r"([A-Za-z_]\w*)", text[j:])
        if not m:
            return "none", "", amp_idx + 1
        name = m.group(1)
        j += m.end()
        if j < len(text) and text[j] == ".":
            j += 1  # consume the name-delimiter dot
        if indirection:
            val = self._symval(name, scope)
            for _ in range(indirection - 1):
                val = self._symval(val.strip(), scope)
            return "val", val, j
        return "sym", name, j

    def _symval(self, name: str, scope: Dict[str, str]) -> str:
        key = name.lower()
        val = scope.get(key)
        if val is None and scope is not self.symbols:
            val = self.symbols.get(key)
        return val if val is not None else ""

    def _resolve(self, text: str, scope: Dict[str, str]) -> str:
        out = []
        i = 0
        while i < len(text):
            if text[i] == "&":
                kind, val, next_i = self._read_symref(text, i, scope)
                if kind == "sym":
                    out.append(self._symval(val, scope))
                    i = next_i
                    continue
                if kind == "val":
                    out.append(val)
                    i = next_i
                    continue
            out.append(text[i])
            i += 1
        return "".join(out)

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
                    spec_end = text.find(";", j)
                    if spec_end == -1:
                        out.append(text[i:])
                        break
                    spec = text[j:spec_end].strip()
                    def_end = _matching_mend(text, i)
                    body = text[spec_end + 1:def_end]
                    mend_at = body.lower().rfind("%mend")
                    if mend_at != -1:
                        body = body[:mend_at]
                    hm = re.match(r"([A-Za-z_]\w*)\s*(?:\((.*)\))?$", spec, flags=re.S)
                    if not hm:
                        i = def_end
                        continue
                    self.macros[hm.group(1).lower()] = {
                        "params": _parse_params(hm.group(2) or ""),
                        "body": body,
                    }
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
                    vname, _, rest = stmt.partition("=")
                    vname = vname.strip().lower()
                    if vname and rest:
                        self.symbols[vname] = self._expand(rest.strip(), scope, depth + 1)
                    i = sem + 1
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
                        out.append(self._invoke(name, arg_text, scope, depth))
                    i = after
                    continue
                if name in _FUNCS:
                    out.append(self._call_func(name, "", scope, depth))
                    i = j
                    continue
                out.append(self._invoke(name, "", scope, depth))
                i = j
                continue
            if text[i] == "&":
                kind, val, next_i = self._read_symref(text, i, scope)
                if kind == "sym":
                    out.append(self._symval(val, scope))
                    i = next_i
                    continue
                if kind == "val":
                    out.append(val)
                    i = next_i
                    continue
                out.append(ch)
                i += 1
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
        return self._expand(_strip_macro_comments(body), scope, depth + 1)

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
    def _invoke(self, name: str, args_text: str, scope, depth) -> str:
        if name not in self.macros:
            return ""
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
        for i, (pname, default) in enumerate(macro["params"]):
            if pname in bind:
                local[pname] = bind[pname]
            elif i < len(positional):
                local[pname] = self._expand(positional[i].strip(), scope, depth + 1)
            elif default:
                local[pname] = self._expand(default, scope, depth + 1)
        return self._expand(macro["body"], local, depth + 1)

    def _call_func(self, name: str, arg_text: str, scope, depth) -> str:
        try:
            if name in ("str", "nrstr", "bquote", "quote", "nrbquote", "dequote"):
                return arg_text
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
    raw = code
    try:
        out = MacroPreprocessor(include_base).preprocess(code)
    except Exception:
        return raw
    if _has_steps(raw) and not _has_steps(out):
        return raw
    return out
