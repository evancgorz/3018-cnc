"""Independent inbound GRBL command parser used by the virtual controller."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re


_WORD = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))")
_COMMENT = re.compile(r"\([^)]*\)|;.*$")


@dataclass(frozen=True)
class ParsedLine:
    raw: str
    words: dict[str, tuple[float, ...]]

    def values(self, letter: str) -> tuple[float, ...]:
        return self.words.get(letter.upper(), ())


class ProtocolError(ValueError):
    pass


def parse_line(raw: str) -> ParsedLine:
    if not isinstance(raw, str):
        raise ProtocolError("command is not text")
    clean = _COMMENT.sub("", raw).strip().upper()
    if not clean:
        raise ProtocolError("empty command")
    if clean.startswith("$"):
        # System commands are parsed by their dedicated handler.
        return ParsedLine(clean, {})
    if clean.startswith("[ESP"):
        return ParsedLine(clean, {})
    matches = list(_WORD.finditer(clean))
    residue = _WORD.sub("", clean).replace(" ", "").replace("\t", "")
    if not matches or residue:
        raise ProtocolError(f"malformed command: {raw.strip()}")
    words: dict[str, list[float]] = {}
    for match in matches:
        letter = match.group(1)
        if letter not in "GMXYZIJKRFSPNTL":
            raise ProtocolError(f"unsupported word {letter}")
        value = float(match.group(2))
        if not math.isfinite(value):
            raise ProtocolError("non-finite command value")
        words.setdefault(letter, []).append(value)
    return ParsedLine(clean, {key: tuple(values) for key, values in words.items()})
