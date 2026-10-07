"""Read a reusable prompt from image metadata without guessing image contents."""

import json
import struct
import zlib


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_TEXT = 64_000


def png_metadata(data):
    """Return PNG text chunks, including compressed tEXt/iTXt variants."""
    if not data.startswith(PNG_SIGNATURE):
        return {}
    result = {}
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        if size > 32_000_000 or offset + size + 12 > len(data):
            break
        kind = data[offset + 4:offset + 8]
        value = data[offset + 8:offset + 8 + size]
        offset += size + 12
        if kind == b"IEND":
            break
        if kind not in (b"tEXt", b"zTXt", b"iTXt"):
            continue
        try:
            key, body = value.split(b"\0", 1)
            if kind == b"zTXt":
                body = zlib.decompressobj().decompress(body[1:], MAX_TEXT + 1)
            elif kind == b"iTXt":
                compressed = body[0]
                body = body[2:]
                _, body = body.split(b"\0", 1)  # language tag
                _, body = body.split(b"\0", 1)  # translated keyword
                if compressed:
                    body = zlib.decompressobj().decompress(body, MAX_TEXT + 1)
            if len(body) <= MAX_TEXT:
                result[key.decode("latin-1").lower()] = body.decode(
                    "utf-8" if kind == b"iTXt" else "latin-1", errors="replace")
        except (ValueError, IndexError, UnicodeError, zlib.error):
            continue
    return result


def _from_json(value):
    if not isinstance(value, dict):
        return ""
    for key in ("prompt", "positive_prompt", "description", "positive"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    for key in ("meta", "metadata"):
        nested = _from_json(value.get(key))
        if nested:
            return nested
    return ""


def prompt_from_metadata(metadata):
    """Return embedded positive prompt only; never present a workflow as a prompt."""
    lowered = {str(key).lower(): str(value) for key, value in metadata.items()}
    for key in ("parameters", "prompt", "description", "comment", "usercomment"):
        value = lowered.get(key, "").strip().replace("\x00", "")
        if not value or len(value) > MAX_TEXT:
            continue
        if value.startswith("{"):
            try:
                value = _from_json(json.loads(value))
            except (ValueError, TypeError):
                continue
        if key == "parameters":
            value = value.split("Negative prompt:", 1)[0]
            value = value.split("\nSteps:", 1)[0]
        value = value.strip()
        if value and len(value) <= 4000:
            return value
    return ""
