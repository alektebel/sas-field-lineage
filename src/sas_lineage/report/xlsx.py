"""
Zero-dependency ``.xlsx`` writer.

The web explorer is deliberately stdlib-only, so the downloadable report cannot
assume ``openpyxl`` (or any spreadsheet library) is installed. This module
writes the small, valid subset of SpreadsheetML needed for a text report:
multiple worksheets, inline strings, a bold header row, frozen header, column
widths and an auto-filter. Excel, LibreOffice and Google Sheets all open it.
"""
from __future__ import annotations

import zipfile
from typing import BinaryIO, List, Sequence, Tuple, Union

__all__ = ["write_xlsx"]

_XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_ODR = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

Sheet = Tuple[str, Sequence[Sequence[object]]]
Target = Union[str, "BinaryIO"]


def _escape(value: object) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _col_letter(index: int) -> str:
    """1-based column index -> ``A``, ``B``, ... ``AA``."""
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _sheet_name(name: str, used: set) -> str:
    clean = "".join("-" if ch in "[]:*?/\\" else ch for ch in name).strip() or "Sheet"
    clean = clean[:31]
    base = clean
    n = 2
    while clean.lower() in used:
        suffix = f" ({n})"
        clean = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(clean.lower())
    return clean


def _content_types(count: int) -> str:
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, count + 1)
    )
    return (
        _XML_HEADER
        + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + overrides
        + '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )


def _root_rels() -> str:
    return (
        _XML_HEADER
        + f'<Relationships xmlns="{_REL_NS}">'
        f'<Relationship Id="rId1" Type="{_ODR}/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook(names: Sequence[str]) -> str:
    sheets = "".join(
        f'<sheet name="{_escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, name in enumerate(names, start=1)
    )
    return (
        _XML_HEADER
        + f'<workbook xmlns="{_MAIN_NS}" xmlns:r="{_ODR}"><sheets>{sheets}</sheets></workbook>'
    )


def _workbook_rels(count: int) -> str:
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="{_ODR}/worksheet" '
        f'Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, count + 1)
    )
    return (
        _XML_HEADER
        + f'<Relationships xmlns="{_REL_NS}">{rels}'
        f'<Relationship Id="rIdStyles" Type="{_ODR}/styles" Target="styles.xml"/>'
        "</Relationships>"
    )


def _styles() -> str:
    return (
        _XML_HEADER
        + f'<styleSheet xmlns="{_MAIN_NS}">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        "</fonts>"
        '<fills count="2">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        "</fills>"
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        "</cellXfs>"
        "</styleSheet>"
    )


def _sheet_xml(rows: Sequence[Sequence[object]]) -> str:
    parts: List[str] = [_XML_HEADER, f'<worksheet xmlns="{_MAIN_NS}">']
    if rows:
        width = max((len(row) for row in rows), default=0)
        height = len(rows)
        parts.append(f'<dimension ref="A1:{_col_letter(width)}{height}"/>')
        parts.append(
            '<sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            "</sheetView></sheetViews>"
        )
        parts.append('<sheetFormatPr defaultRowHeight="15"/>')
        if width:
            cols = []
            for c in range(width):
                longest = max((len(str(row[c])) for row in rows if c < len(row)), default=0)
                cols.append(
                    f'<col min="{c + 1}" max="{c + 1}" '
                    f'width="{min(60, max(9, longest + 2))}" customWidth="1"/>'
                )
            parts.append("<cols>" + "".join(cols) + "</cols>")
        body: List[str] = ["<sheetData>"]
        for r, row in enumerate(rows, start=1):
            style = ' s="1"' if r == 1 else ""
            cells = []
            for c, value in enumerate(row, start=1):
                ref = f"{_col_letter(c)}{r}"
                cells.append(
                    f'<c r="{ref}" t="inlineStr"{style}>'
                    f'<is><t xml:space="preserve">{_escape(value)}</t></is></c>'
                )
            body.append(f'<row r="{r}">' + "".join(cells) + "</row>")
        body.append("</sheetData>")
        parts.append("".join(body))
        parts.append(f'<autoFilter ref="A1:{_col_letter(width)}{height}"/>')
    else:
        parts.append("<sheetData/>")
    parts.append("</worksheet>")
    return "".join(parts)


def write_xlsx(target: Target, sheets: Sequence[Sheet]) -> None:
    """Write ``sheets`` (``(name, rows)``) to ``target`` as a workbook.

    ``target`` is a path or any binary file-like object (e.g. ``io.BytesIO``).
    """
    if not sheets:
        sheets = [("Sheet1", [])]
    used: set = set()
    named = [(_sheet_name(name, used), rows) for name, rows in sheets]

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types(len(named)))
        zf.writestr("_rels/.rels", _root_rels())
        zf.writestr("xl/workbook.xml", _workbook([name for name, _ in named]))
        zf.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(named)))
        zf.writestr("xl/styles.xml", _styles())
        for i, (_name, rows) in enumerate(named, start=1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(rows))
