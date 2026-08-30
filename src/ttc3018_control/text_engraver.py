from __future__ import annotations

from dataclasses import dataclass
import math


Stroke = tuple[tuple[float, float], ...]
FONT_NAMES = ("Simple", "Rounded", "Technical", "Italic", "Script", "Playful", "Cursive")


# Compact single-line capitals. Lowercase input intentionally uses the same
# durable engraving forms so small lettering remains legible.
GLYPHS: dict[str, tuple[Stroke, ...]] = {
    "A": (((0, 0), (0.5, 1), (1, 0)), ((0.2, 0.4), (0.8, 0.4))),
    "B": (((0, 0), (0, 1), (0.62, 1), (0.9, 0.82), (0.9, 0.62), (0.62, 0.5), (0, 0.5)), ((0.62, 0.5), (0.95, 0.35), (0.95, 0.15), (0.65, 0), (0, 0))),
    "C": (((0.95, 0.85), (0.72, 1), (0.25, 1), (0, 0.75), (0, 0.25), (0.25, 0), (0.72, 0), (0.95, 0.15)),),
    "D": (((0, 0), (0, 1), (0.55, 1), (0.95, 0.72), (0.95, 0.28), (0.55, 0), (0, 0)),),
    "E": (((0.95, 1), (0, 1), (0, 0), (0.95, 0)), ((0, 0.5), (0.72, 0.5))),
    "F": (((0, 0), (0, 1), (0.95, 1)), ((0, 0.5), (0.72, 0.5))),
    "G": (((0.95, 0.82), (0.72, 1), (0.25, 1), (0, 0.75), (0, 0.25), (0.25, 0), (0.75, 0), (0.95, 0.2), (0.95, 0.48), (0.55, 0.48)),),
    "H": (((0, 0), (0, 1)), ((1, 0), (1, 1)), ((0, 0.5), (1, 0.5))),
    "I": (((0.15, 1), (0.85, 1)), ((0.5, 1), (0.5, 0)), ((0.15, 0), (0.85, 0))),
    "J": (((0.1, 0.2), (0.28, 0), (0.62, 0), (0.82, 0.2), (0.82, 1)), ((0.5, 1), (1, 1))),
    "K": (((0, 0), (0, 1)), ((1, 1), (0, 0.42)), ((0.38, 0.62), (1, 0))),
    "L": (((0, 1), (0, 0), (0.95, 0)),),
    "M": (((0, 0), (0, 1), (0.5, 0.42), (1, 1), (1, 0)),),
    "N": (((0, 0), (0, 1), (1, 0), (1, 1)),),
    "O": (((0.25, 0), (0, 0.25), (0, 0.75), (0.25, 1), (0.75, 1), (1, 0.75), (1, 0.25), (0.75, 0), (0.25, 0)),),
    "P": (((0, 0), (0, 1), (0.65, 1), (0.95, 0.8), (0.95, 0.62), (0.65, 0.5), (0, 0.5)),),
    "Q": (((0.25, 0), (0, 0.25), (0, 0.75), (0.25, 1), (0.75, 1), (1, 0.75), (1, 0.25), (0.75, 0), (0.25, 0)), ((0.58, 0.25), (1.05, -0.12))),
    "R": (((0, 0), (0, 1), (0.65, 1), (0.95, 0.8), (0.95, 0.62), (0.65, 0.5), (0, 0.5)), ((0.52, 0.5), (1, 0))),
    "S": (((0.95, 0.82), (0.72, 1), (0.25, 1), (0.02, 0.8), (0.02, 0.62), (0.25, 0.5), (0.72, 0.5), (0.95, 0.35), (0.95, 0.18), (0.72, 0), (0.25, 0), (0.02, 0.18)),),
    "T": (((0, 1), (1, 1)), ((0.5, 1), (0.5, 0))),
    "U": (((0, 1), (0, 0.25), (0.25, 0), (0.75, 0), (1, 0.25), (1, 1)),),
    "V": (((0, 1), (0.5, 0), (1, 1)),),
    "W": (((0, 1), (0.22, 0), (0.5, 0.55), (0.78, 0), (1, 1)),),
    "X": (((0, 1), (1, 0)), ((0, 0), (1, 1))),
    "Y": (((0, 1), (0.5, 0.5), (1, 1)), ((0.5, 0.5), (0.5, 0))),
    "Z": (((0, 1), (1, 1), (0, 0), (1, 0)),),
    "0": (((0.25, 0), (0, 0.25), (0, 0.75), (0.25, 1), (0.75, 1), (1, 0.75), (1, 0.25), (0.75, 0), (0.25, 0)), ((0.2, 0.15), (0.8, 0.85))),
    "1": (((0.25, 0.78), (0.5, 1), (0.5, 0)), ((0.2, 0), (0.82, 0))),
    "2": (((0.05, 0.78), (0.25, 1), (0.72, 1), (0.95, 0.78), (0.95, 0.62), (0, 0), (1, 0)),),
    "3": (((0.05, 0.85), (0.25, 1), (0.72, 1), (0.95, 0.8), (0.72, 0.5), (0.95, 0.25), (0.72, 0), (0.25, 0), (0.05, 0.15)),),
    "4": (((0.75, 0), (0.75, 1), (0, 0.32), (1, 0.32)),),
    "5": (((0.95, 1), (0.1, 1), (0.02, 0.52), (0.7, 0.52), (0.95, 0.35), (0.95, 0.18), (0.72, 0), (0.25, 0), (0.02, 0.18)),),
    "6": (((0.88, 0.85), (0.7, 1), (0.3, 1), (0.05, 0.72), (0.05, 0.25), (0.25, 0), (0.72, 0), (0.95, 0.22), (0.95, 0.42), (0.72, 0.58), (0.05, 0.58)),),
    "7": (((0, 1), (1, 1), (0.25, 0)),),
    "8": (((0.25, 0.5), (0.05, 0.68), (0.05, 0.82), (0.25, 1), (0.72, 1), (0.95, 0.82), (0.95, 0.68), (0.72, 0.5), (0.25, 0.5), (0.02, 0.32), (0.02, 0.18), (0.25, 0), (0.72, 0), (0.98, 0.18), (0.98, 0.32), (0.72, 0.5)),),
    "9": (((0.92, 0.42), (0.25, 0.42), (0.05, 0.58), (0.05, 0.8), (0.28, 1), (0.75, 1), (0.95, 0.75), (0.95, 0.28), (0.7, 0), (0.3, 0), (0.1, 0.15)),),
    "-": (((0.15, 0.5), (0.85, 0.5)),),
    "_": (((0, 0), (1, 0)),),
    ".": (((0.48, 0), (0.52, 0)),),
    ",": (((0.55, 0.08), (0.42, -0.16)),),
    "!": (((0.5, 1), (0.5, 0.22)), ((0.48, 0), (0.52, 0))),
    "?": (((0.05, 0.78), (0.25, 1), (0.72, 1), (0.95, 0.78), (0.95, 0.62), (0.5, 0.4), (0.5, 0.22)), ((0.48, 0), (0.52, 0))),
    ":": (((0.48, 0.72), (0.52, 0.72)), ((0.48, 0.12), (0.52, 0.12))),
    "/": (((0, 0), (1, 1)),),
    "+": (((0.5, 0.15), (0.5, 0.85)), ((0.15, 0.5), (0.85, 0.5))),
    "=": (((0.15, 0.65), (0.85, 0.65)), ((0.15, 0.35), (0.85, 0.35))),
    "'": (((0.5, 1), (0.42, 0.72)),),
    '"': (((0.3, 1), (0.25, 0.72)), ((0.7, 1), (0.65, 0.72))),
    "(": (((0.7, 1), (0.4, 0.75), (0.3, 0.5), (0.4, 0.25), (0.7, 0)),),
    ")": (((0.3, 1), (0.6, 0.75), (0.7, 0.5), (0.6, 0.25), (0.3, 0)),),
}


@dataclass(frozen=True)
class TextEngraving:
    gcode: str
    width: float
    height: float
    stroke_count: int
    strokes: tuple[Stroke, ...]


def generate_text_gcode(
    text: str,
    *,
    font: str = "Simple",
    text_height: float = 8.0,
    depth: float = -0.3,
    safe_z: float = 3.0,
    cut_feed: float = 300.0,
    plunge_feed: float = 100.0,
    letter_spacing: float = 0.18,
    line_spacing: float = 1.4,
    alignment: str = "Left",
    spindle_rpm: int | None = None,
) -> TextEngraving:
    if not text.strip():
        raise ValueError("Enter text to engrave")
    if font not in FONT_NAMES:
        raise ValueError("Unknown engraving font")
    if not 0.5 <= text_height <= 100:
        raise ValueError("Text height must be between 0.5 and 100 mm")
    if not -20 <= depth < 0:
        raise ValueError("Engraving depth must be below work Z0 and no deeper than 20 mm")
    if not 0.1 <= safe_z <= 100:
        raise ValueError("Safe Z must be between 0.1 and 100 mm")
    if not 1 <= cut_feed <= 3000 or not 1 <= plunge_feed <= 1000:
        raise ValueError("Cut feed must be 1–3000 and plunge feed 1–1000 mm/min")
    if not 0 <= letter_spacing <= 2 or not 1 <= line_spacing <= 3:
        raise ValueError("Letter spacing must be 0–2 and line spacing 1–3")
    if alignment not in {"Left", "Center", "Right"}:
        raise ValueError("Alignment must be Left, Center, or Right")
    if spindle_rpm is not None and not 1 <= spindle_rpm <= 24000:
        raise ValueError("Spindle RPM must be between 1 and 24000")

    lines = text.splitlines() or [text]
    x_scale = 0.48 if font == "Technical" else (0.68 if font == "Cursive" else 0.62)
    glyph_width = text_height * x_scale
    advance = glyph_width + text_height * letter_spacing
    widths = [max(0.0, len(line) * advance - text_height * letter_spacing) for line in lines]
    overall_width = max(widths, default=0.0)
    overall_height = text_height + (len(lines) - 1) * text_height * line_spacing
    all_strokes: list[Stroke] = []

    for line_index, line in enumerate(lines):
        line_width = widths[line_index]
        if alignment == "Center":
            line_x = (overall_width - line_width) / 2
        elif alignment == "Right":
            line_x = overall_width - line_width
        else:
            line_x = 0.0
        baseline = overall_height - text_height - line_index * text_height * line_spacing
        for char_index, character in enumerate(line.upper()):
            if character == " ":
                continue
            glyph = GLYPHS.get(character)
            if glyph is None:
                raise ValueError(f"Character {character!r} is not supported by the bundled engraving fonts")
            origin_x = line_x + char_index * advance
            for stroke in glyph:
                transformed = tuple((origin_x + x * glyph_width, baseline + y * text_height) for x, y in stroke)
                if font in {"Rounded", "Script", "Playful", "Cursive"} and len(transformed) > 2:
                    transformed = _round_corners(transformed, min(glyph_width, text_height) * 0.08)
                if font in {"Italic", "Script", "Cursive"}:
                    transformed = tuple(
                        (x + (y - baseline) * 0.22, y) for x, y in transformed
                    )
                if font == "Playful":
                    bounce = (0.08 if char_index % 2 else 0.0) * text_height
                    transformed = tuple(
                        (x + math.sin((y - baseline) / text_height * math.pi) * glyph_width * 0.07, y + bounce)
                        for x, y in transformed
                    )
                all_strokes.append(transformed)
            if font == "Cursive" and char_index + 1 < len(line) and line[char_index + 1] != " ":
                connector_y = baseline + text_height * 0.16
                all_strokes.append(
                    (
                        (origin_x + glyph_width * 0.78, connector_y),
                        (origin_x + advance + glyph_width * 0.12, connector_y),
                    )
                )

    min_x = min((x for stroke in all_strokes for x, _y in stroke), default=0.0)
    min_y = min((y for stroke in all_strokes for _x, y in stroke), default=0.0)
    shift_x = -min(0.0, min_x)
    shift_y = -min(0.0, min_y)
    if shift_x or shift_y:
        all_strokes = [tuple((x + shift_x, y + shift_y) for x, y in stroke) for stroke in all_strokes]
    maximum_x = max((x for stroke in all_strokes for x, _y in stroke), default=0.0)
    maximum_y = max((y for stroke in all_strokes for _x, y in stroke), default=0.0)
    overall_width = max(overall_width + shift_x, maximum_x)
    overall_height = max(overall_height + shift_y, maximum_y)

    commands = [
        "; Generated by TTC 3018 Text Engraver",
        f"; Text height {text_height:g} mm, depth {depth:g} mm, font {font}",
        "G21",
        "G17",
        "G90",
        "G94",
        f"G0 Z{safe_z:g}",
    ]
    if spindle_rpm is not None:
        commands.insert(-1, f"M3 S{spindle_rpm}")
    for stroke in all_strokes:
        first = stroke[0]
        commands.append(f"G0 X{_fmt(first[0])} Y{_fmt(first[1])}")
        commands.append(f"G1 Z{depth:g} F{plunge_feed:g}")
        for x, y in stroke[1:]:
            commands.append(f"G1 X{_fmt(x)} Y{_fmt(y)} F{cut_feed:g}")
        commands.append(f"G0 Z{safe_z:g}")
    commands.extend((f"G0 Z{safe_z:g}", "G0 X0 Y0", "M5", "M2"))
    return TextEngraving(
        "\n".join(commands) + "\n",
        overall_width,
        overall_height,
        len(all_strokes),
        tuple(all_strokes),
    )


def _fmt(value: float) -> str:
    if math.isclose(value, 0, abs_tol=0.0000005):
        value = 0.0
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _round_corners(points: Stroke, radius: float) -> Stroke:
    result: list[tuple[float, float]] = [points[0]]
    for previous, corner, following in zip(points, points[1:-1], points[2:]):
        incoming = _toward(corner, previous, radius)
        outgoing = _toward(corner, following, radius)
        result.append(incoming)
        for step in range(1, 4):
            t = step / 4
            one_minus = 1 - t
            result.append(
                (
                    one_minus * one_minus * incoming[0] + 2 * one_minus * t * corner[0] + t * t * outgoing[0],
                    one_minus * one_minus * incoming[1] + 2 * one_minus * t * corner[1] + t * t * outgoing[1],
                )
            )
        result.append(outgoing)
    result.append(points[-1])
    return tuple(result)


def _toward(origin: tuple[float, float], target: tuple[float, float], distance: float) -> tuple[float, float]:
    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    length = math.hypot(dx, dy)
    if length <= distance or length == 0:
        return ((origin[0] + target[0]) / 2, (origin[1] + target[1]) / 2)
    ratio = distance / length
    return origin[0] + dx * ratio, origin[1] + dy * ratio
