"""
Extract SAS source from an uploaded SAS Enterprise Guide project (``.egp``).

``.egp`` files come in two shapes in the wild:

* a ZIP container holding one or more ``.sas`` programs (plus a manifest), and
* the native SAS EG OLE compound document, where the SAS code lives inside
  streams (usually as UTF-16).

This module is standard-library only. It reads the ZIP case exactly, enumerates
OLE streams with a minimal compound-file reader, and falls back to a raw byte
scan (UTF-8 / UTF-16LE / Latin-1) for anything else. Text is then reduced to
contiguous ``DATA`` / ``PROC`` / ``%macro`` blocks so manifests and markup do not
leak into the parsed program.
"""
from __future__ import annotations

import io
import json
import re
import struct
import zipfile
from typing import Dict, List, Tuple

__all__ = ["extract_sas"]

_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ENDOFCHAIN = 0xFFFFFFFE

# Lines that begin a SAS step (or its setup) and lines that close one.
_STEP_START_RE = re.compile(r"^\s*(?:data|proc|%macro|%let|libname)\b", re.IGNORECASE)
_STEP_END_RE = re.compile(r"\b(?:run|quit)\s*;", re.IGNORECASE)
_SAS_MARKER_RE = re.compile(r"\b(?:data|proc|%macro)\b", re.IGNORECASE)


def _decode(data: bytes) -> str:
    """Best-effort decode of a stream that may be UTF-8, UTF-16LE or binary."""
    sample = data[:4096]
    if len(sample) >= 2:
        pairs = len(sample) // 2
        zeros_even = sum(1 for i in range(0, len(sample), 2) if sample[i] == 0)
        zeros_odd = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0)
        # ASCII text stored as UTF-16 has NULs on one consistent parity.
        if zeros_odd > pairs * 0.3 and zeros_odd > zeros_even:
            try:
                return data.decode("utf-16-le")
            except UnicodeDecodeError:
                pass
        if zeros_even > pairs * 0.3 and zeros_even > zeros_odd:
            try:
                return data.decode("utf-16-be")
            except UnicodeDecodeError:
                pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if data.count(b"\x00") > len(data) // 8:
        try:
            return data.decode("utf-16-le")
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1", "replace")


def _collect_sas_from_text(text: str) -> str:
    """Keep only contiguous SAS step blocks from a mixed text blob."""
    if not text:
        return ""
    text = text.replace("\x00", "")
    if not _SAS_MARKER_RE.search(text):
        return ""
    blocks: List[str] = []
    current: List[str] = []
    in_code = False
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        stripped = line.strip()
        if not in_code:
            if _STEP_START_RE.match(stripped):
                in_code = True
            else:
                continue
        current.append(line)
        if _STEP_END_RE.search(stripped):
            in_code = False
            block = "\n".join(current).strip()
            if block:
                blocks.append(block)
            current = []
    if current:
        block = "\n".join(current).strip()
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- #
# Minimal OLE / Compound File Binary reader
# --------------------------------------------------------------------------- #
def _read_ole_streams(data: bytes) -> List[Tuple[str, bytes]]:
    """Return ``(stream_name, bytes)`` for every stream in an OLE container."""
    if len(data) < 512 or data[:8] != _CFB_MAGIC:
        return []
    sector_shift = struct.unpack_from("<H", data, 30)[0]
    mini_shift = struct.unpack_from("<H", data, 32)[0]
    if not (1 <= sector_shift <= 20) or not (1 <= mini_shift <= 20):
        return []
    sector_size = 1 << sector_shift
    mini_size = 1 << mini_shift

    num_fat = struct.unpack_from("<I", data, 44)[0]
    dir_start = struct.unpack_from("<I", data, 48)[0]
    mini_cutoff = struct.unpack_from("<I", data, 56)[0]
    mini_fat_start = struct.unpack_from("<I", data, 60)[0]
    num_mini_fat = struct.unpack_from("<I", data, 64)[0]
    difat_start = struct.unpack_from("<I", data, 68)[0]
    num_difat = struct.unpack_from("<I", data, 72)[0]

    # DIFAT -> list of FAT sector numbers.
    difat = list(struct.unpack_from("<109I", data, 76))
    sector = difat_start
    for _ in range(min(num_difat, 1_000_000)):
        if sector >= _ENDOFCHAIN:
            break
        offset = (sector + 1) * sector_size
        if offset + sector_size > len(data):
            break
        entries = struct.unpack_from(f"<{sector_size // 4}I", data, offset)
        difat.extend(entries[:-1])
        sector = entries[-1]

    # FAT -> next-sector table.
    fat: List[int] = []
    for fat_sector in difat[:num_fat]:
        if fat_sector >= _ENDOFCHAIN:
            continue
        offset = (fat_sector + 1) * sector_size
        if offset + sector_size > len(data):
            continue
        fat.extend(struct.unpack_from(f"<{sector_size // 4}I", data, offset))

    def chain(start: int) -> List[int]:
        out: List[int] = []
        node = start
        for _ in range(1_000_000):
            if node >= _ENDOFCHAIN or node >= len(fat):
                break
            out.append(node)
            node = fat[node]
        return out

    def read_chain(start: int, size: int | None = None) -> bytes:
        chunks = []
        for node in chain(start):
            offset = (node + 1) * sector_size
            chunks.append(data[offset:offset + sector_size])
        buf = b"".join(chunks)
        return buf if size is None else buf[:size]

    # Directory entries.
    dir_bytes = read_chain(dir_start)
    entries: List[Tuple[str, int, int, int]] = []
    for i in range(0, max(0, len(dir_bytes) - 127), 128):
        entry = dir_bytes[i:i + 128]
        name_len = struct.unpack_from("<H", entry, 64)[0]
        if name_len < 2 or name_len > 64:
            continue
        name = entry[:name_len - 2].decode("utf-16-le", "replace")
        obj_type = entry[66]
        start = struct.unpack_from("<I", entry, 116)[0]
        size = struct.unpack_from("<Q", entry, 120)[0]
        entries.append((name, obj_type, start, size))

    root = next((e for e in entries if e[1] == 5), None)
    mini_stream = read_chain(root[2], root[3]) if root else b""

    mini_fat: List[int] = []
    if num_mini_fat:
        for node in chain(mini_fat_start):
            offset = (node + 1) * sector_size
            mini_fat.extend(struct.unpack_from(f"<{sector_size // 4}I", data, offset))

    def read_mini(start: int, size: int) -> bytes:
        chunks = []
        node = start
        for _ in range(1_000_000):
            if node >= _ENDOFCHAIN or node >= len(mini_fat):
                break
            offset = node * mini_size
            chunks.append(mini_stream[offset:offset + mini_size])
            node = mini_fat[node]
        return b"".join(chunks)[:size]

    streams: List[Tuple[str, bytes]] = []
    for name, obj_type, start, size in entries:
        if obj_type != 2 or size == 0:
            continue
        if size < mini_cutoff:
            blob = read_mini(start, size)
        else:
            blob = read_chain(start, size)
        streams.append((name, blob))
    return streams


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def _read_manifest(archive: "zipfile.ZipFile", names: List[str]) -> Dict[str, object]:
    """Read an EGP ``manifest.json`` (when present) as a completeness oracle."""
    for name in names:
        if name.rsplit("/", 1)[-1].lower() != "manifest.json":
            continue
        try:
            data = json.loads(_decode(archive.read(name)))
        except (ValueError, KeyError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        tables = data.get("tables_produced") or []
        layers = []
        for layer in data.get("layers") or []:
            if isinstance(layer, dict):
                layers.append({"id": layer.get("id"), "name": layer.get("name")})
        return {
            "manifest_name": data.get("name"),
            "manifest_tables": [str(t) for t in tables if t],
            "manifest_layers": layers,
        }
    return {}


def _from_zip(data: bytes) -> Tuple[str, Dict[str, object]] | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            manifest = _read_manifest(archive, names)
            # Keep the archive (start-to-finish) order: an EGP's programs may
            # define a macro in one program and use it in a later one.
            sas_names = [n for n in names if n.lower().endswith(".sas")]
            if sas_names:
                parts = [_decode(archive.read(n)) for n in sas_names]
                source = "\n\n".join(p for p in parts if p.strip())
                return source, {"format": "zip", "programs": sas_names, **manifest}
            parts = []
            for name in names:
                block = _collect_sas_from_text(_decode(archive.read(name)))
                if block:
                    parts.append(block)
            return "\n\n".join(parts), {"format": "zip", "programs": [], **manifest}
    except (zipfile.BadZipFile, OSError):
        return None


def _from_ole(data: bytes) -> Tuple[str, Dict[str, object]] | None:
    try:
        streams = _read_ole_streams(data)
    except Exception:
        return None
    parts: List[str] = []
    names: List[str] = []
    for name, blob in streams:
        block = _collect_sas_from_text(_decode(blob))
        if block:
            parts.append(block)
            names.append(name or "(unnamed)")
    if not parts:
        return None
    return "\n\n".join(parts), {"format": "ole", "programs": names}


def extract_sas(data: bytes) -> Tuple[str, Dict[str, object]]:
    """Return ``(sas_source, info)`` for an uploaded ``.egp`` / archive.

    ``info`` carries the container ``format``, the ``programs`` found and the
    character count, so the UI can report what was extracted.
    """
    if data[:2] == b"PK":
        result = _from_zip(data)
        if result is not None:
            source, info = result
            info["chars"] = len(source)
            return source, info
    if data[:8] == _CFB_MAGIC:
        result = _from_ole(data)
        if result is not None:
            source, info = result
            info["chars"] = len(source)
            return source, info
    source = _collect_sas_from_text(_decode(data))
    return source, {"format": "text", "programs": [], "chars": len(source)}
