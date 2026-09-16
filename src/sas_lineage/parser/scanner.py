"""Lexical boundaries shared by SAS parsing and table-name extraction.

This is a source scanner, not a macro processor. Offsets refer to the input
string, including comments. DATA lines are opaque, and quoted semicolons do
not terminate a statement.
"""
from dataclasses import dataclass
import re
from typing import List, Tuple


@dataclass(frozen=True)
class ScanIssue:
    code: str
    message: str
    line: int


@dataclass(frozen=True)
class Statement:
    text: str
    line: int
    start: int
    end: int
    terminated: bool = True


@dataclass(frozen=True)
class Token:
    text: str
    kind: str
    start: int
    end: int

    @property
    def upper(self) -> str:
        return self.text.upper() if self.kind == "word" else ""


def quoted_end(text: str, start: int) -> int:
    """Return the end of a SAS quoted string, respecting doubled quotes."""
    quote = text[start]
    i = start + 1
    while i < len(text):
        if text[i] == quote:
            if i + 1 < len(text) and text[i + 1] == quote:
                i += 2
                continue
            return i + 1
        i += 1
    return len(text)


def strip_comments(source: str) -> str:
    """Blank comments without changing line/offset coordinates or literals."""
    chars = list(source)
    i = 0
    at_start = True
    while i < len(source):
        if source[i] in "\"'":
            i = quoted_end(source, i)
            at_start = False
            continue
        end = None
        if source.startswith('/*', i):
            closing = source.find('*/', i + 2)
            end = len(source) if closing == -1 else closing + 2
        elif source.startswith('%*', i) or (at_start and source[i] == '*'):
            closing = source.find(';', i)
            end = len(source) if closing == -1 else closing + 1
        if end is not None:
            for index in range(i, end):
                if chars[index] != '\n':
                    chars[index] = ' '
            i = end
            continue
        if source[i] == ';':
            at_start = True
        elif not source[i].isspace():
            at_start = False
        i += 1
    return ''.join(chars)


def scan_statements(source: str) -> Tuple[List[Statement], List[ScanIssue]]:
    statements: List[Statement] = []
    issues: List[ScanIssue] = []
    pieces: List[str] = []
    i, line, start, start_line = 0, 1, None, 1
    cards = None
    while i < len(source):
        if cards is not None:
            # DATALINES4 permits embedded semicolons; only ;;;; ends it.
            end = source.find("\n", i)
            end = len(source) if end == -1 else end + 1
            row = source[i:end]
            if row.strip() == cards:
                cards = None
            line += row.count("\n")
            i = end
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end == -1:
                issues.append(ScanIssue("unterminated_comment", "Block comment has no closing */.", line))
                end = len(source)
            else:
                end += 2
            comment = source[i:end]
            pieces.append("".join("\n" if c == "\n" else " " for c in comment))
            line += comment.count("\n")
            i = end
            continue
        if start is None and (source[i] == "*" or source.startswith("%*", i)):
            end = source.find(";", i)
            end = len(source) if end == -1 else end + 1
            line += source[i:end].count("\n")
            pieces.clear()
            i = end
            continue
        char = source[i]
        if start is None and not char.isspace() and char != ";":
            start, start_line = i, line
            pieces.clear()
        if char in "\"'":
            end = quoted_end(source, i)
            tail = source[i + 1:end]
            trailing_quotes = len(tail) - len(tail.rstrip(char))
            if end == len(source) and trailing_quotes % 2 == 0:
                issues.append(ScanIssue("unterminated_string", "Quoted string is not closed.", line))
            pieces.append(source[i:end])
            line += source[i:end].count("\n")
            i = end
            continue
        if char == ";":
            text = "".join(pieces).strip()
            if text:
                statements.append(Statement(text, start_line, start, i + 1))
                if re.fullmatch(r"(?:datalines|cards)(4)?", text, re.I):
                    cards = ";;;;" if text.endswith("4") else ";"
            pieces.clear()
            start = None
        else:
            pieces.append(char)
        line += char == "\n"
        i += 1
    text = "".join(pieces).strip()
    if text:
        statements.append(Statement(text, start_line, start, len(source), False))
        issues.append(ScanIssue("unterminated_statement", "Statement has no terminating semicolon.", start_line))
    if cards is not None:
        issues.append(ScanIssue("unterminated_datalines", "Inline data has no closing delimiter.", line))
    return statements, issues


def tokenize(text: str) -> List[Token]:
    """Tokenize statement text without interpreting strings or macro values."""
    tokens: List[Token] = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        start = i
        if text[i] in "\"'":
            i = quoted_end(text, i)
            kind = "string"
            if i < len(text) and text[i].lower() == "n":
                i += 1
                kind = "name_literal"
        elif text[i].isalpha() or text[i] == "_":
            i += 1
            while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                i += 1
            kind = "word"
        elif text[i] == "&":
            i += 1
            while i < len(text) and text[i] == "&":
                i += 1
            while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                i += 1
            if i < len(text) and text[i] == ".":
                i += 1
            kind = "macro"
        elif text[i] == "%" and i + 1 < len(text) and text[i + 1].isalpha():
            i += 2
            while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                i += 1
            kind = "macro"
        elif text[i].isdigit():
            i += 1
            while i < len(text) and text[i].isdigit():
                i += 1
            kind = "number"
        else:
            i += 1
            kind = "punctuation"
        tokens.append(Token(text[start:i], kind, start, i))
    return tokens


def read_name(tokens: List[Token], index: int) -> Tuple[str, int]:
    """Read a qualified or symbolic dataset name without truncating it."""
    if index >= len(tokens) or tokens[index].kind not in {"word", "name_literal", "macro"}:
        return "", index
    parts = [tokens[index].text]
    last_end = tokens[index].end
    index += 1
    while index < len(tokens):
        token = tokens[index]
        if token.text == "." and index + 1 < len(tokens):
            following = tokens[index + 1]
            if following.kind in {"word", "name_literal", "macro"}:
                parts.extend([".", following.text])
                last_end = following.end
                index += 2
                continue
        if token.start == last_end and token.kind in {"word", "macro", "number"}:
            parts.append(token.text)
            last_end = token.end
            index += 1
            continue
        break
    return "".join(parts), index


def skip_group(tokens: List[Token], index: int) -> int:
    """Skip parenthesized dataset options or expressions."""
    depth = 0
    while index < len(tokens):
        text = tokens[index].text
        depth += text == "("
        depth -= text == ")"
        index += 1
        if depth == 0:
            break
    return index


def dataset_list(text: str) -> Tuple[List[str], bool]:
    """Read explicit datasets; return an incomplete flag for unsupported lists."""
    tokens = tokenize(text)
    names: List[str] = []
    i = 0
    incomplete = False
    while i < len(tokens):
        if tokens[i].text == "/":
            break
        if i + 1 < len(tokens) and tokens[i + 1].text == "=":
            break  # SET/DATA statement options, e.g. END=, NOBS=, VIEW=.
        name, after = read_name(tokens, i)
        if not name:
            incomplete = True
            break
        if after < len(tokens) and tokens[after].text in {":", "-"}:
            incomplete = True
            break  # Prefix/range lists require a catalog or list expansion.
        names.append(name)
        i = after
        if i < len(tokens) and tokens[i].text == "(":
            i = skip_group(tokens, i)
    return names, incomplete


def dataset_options(text: str, names: Tuple[str, ...]) -> List[Tuple[str, str]]:
    """Read top-level DATA=/OUT= etc., ignoring options inside expressions."""
    tokens = tokenize(text)
    result: List[Tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        if tokens[i].text == "(":
            i = skip_group(tokens, i)
            continue
        if tokens[i].upper in names and i + 1 < len(tokens) and tokens[i + 1].text == "=":
            name, after = read_name(tokens, i + 2)
            if name:
                result.append((tokens[i].upper, name))
                i = after
                continue
        i += 1
    return result
