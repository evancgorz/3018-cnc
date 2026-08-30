from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re


_COMMENT = re.compile(r"\([^)]*\)|;.*$")
_WORD = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))")
_ALLOWED_G = {0, 1, 2, 3, 4, 17, 21, 40, 49, 54, 80, 90, 91, 94}
_ALLOWED_M = {0, 1, 2, 3, 4, 5, 30}
_ALLOWED_LETTERS = set("GMXYZIJKRFSPNT")


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Segment:
    start: Point
    end: Point
    rapid: bool


@dataclass(frozen=True)
class Bounds:
    minimum: Point
    maximum: Point

    @property
    def size(self) -> Point:
        return Point(
            self.maximum.x - self.minimum.x,
            self.maximum.y - self.minimum.y,
            self.maximum.z - self.minimum.z,
        )


@dataclass(frozen=True)
class GCodeProgram:
    path: Path
    commands: tuple[str, ...]
    segments: tuple[Segment, ...]
    bounds: Bounds


class GCodeError(ValueError):
    pass


def _clean(raw: str) -> str:
    return _COMMENT.sub("", raw).strip().upper()


def _number_code(value: float) -> int:
    rounded = round(value)
    if not math.isclose(value, rounded, abs_tol=1e-9):
        raise GCodeError(f"unsupported fractional command code {value:g}")
    return int(rounded)


def load_gcode(path: Path) -> GCodeProgram:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise GCodeError("G-code file must be UTF-8 or ASCII text") from exc
    return parse_gcode(text, path)


def parse_gcode(text: str, path: Path | None = None) -> GCodeProgram:
    commands: list[str] = []
    segments: list[Segment] = []
    position = Point(0.0, 0.0, 0.0)
    absolute = True
    motion = 0
    points = [position]

    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = _clean(raw)
        if not line or line == "%":
            continue
        if line.startswith("$"):
            raise GCodeError(f"line {line_number}: GRBL system commands are not allowed in a job")

        matches = list(_WORD.finditer(line))
        residue = _WORD.sub("", line).replace(" ", "").replace("\t", "")
        if not matches or residue:
            raise GCodeError(f"line {line_number}: malformed or unsupported text: {raw.strip()}")

        words: dict[str, list[float]] = {}
        for match in matches:
            letter = match.group(1).upper()
            if letter not in _ALLOWED_LETTERS:
                raise GCodeError(f"line {line_number}: {letter} words are not supported")
            words.setdefault(letter, []).append(float(match.group(2)))

        for value in words.get("G", []):
            if 38 <= value < 39:
                raise GCodeError(
                    f"line {line_number}: G{value:g} probing is unsafe motion without a commissioned probe"
                )
            code = _number_code(value)
            if code == 20:
                raise GCodeError(f"line {line_number}: inch mode (G20) is not allowed; export metric G-code")
            if code in {10, 28, 30, 53, 92}:
                raise GCodeError(f"line {line_number}: G{code} can alter references or initiate unsafe motion")
            if code not in _ALLOWED_G:
                raise GCodeError(f"line {line_number}: unsupported G-code G{code}")
            if code in {0, 1, 2, 3}:
                motion = code
            elif code == 90:
                absolute = True
            elif code == 91:
                absolute = False

        for value in words.get("M", []):
            code = _number_code(value)
            if code == 6:
                raise GCodeError(f"line {line_number}: tool changes are not supported")
            if code not in _ALLOWED_M:
                raise GCodeError(f"line {line_number}: unsupported M-code M{code}")

        target = Point(
            _target(position.x, words.get("X"), absolute),
            _target(position.y, words.get("Y"), absolute),
            _target(position.z, words.get("Z"), absolute),
        )
        has_axis = any(axis in words for axis in "XYZ")
        if has_axis:
            if motion in {2, 3}:
                if "R" in words or not ({"I", "J"} & words.keys()):
                    raise GCodeError(
                        f"line {line_number}: arcs must use I/J center offsets; R arcs are not supported in the MVP"
                    )
                arc_points = _arc_points(position, target, words, clockwise=motion == 2, line_number=line_number)
                for start, end in zip(arc_points, arc_points[1:]):
                    segments.append(Segment(start, end, False))
                points.extend(arc_points[1:])
            else:
                segments.append(Segment(position, target, motion == 0))
                points.append(target)
            position = target

        commands.append(" ".join(line.split()))

    if not commands:
        raise GCodeError("The file contains no executable G-code")
    if not segments:
        raise GCodeError("The file contains no XYZ motion")

    minimum = Point(*(min(getattr(point, axis) for point in points) for axis in "xyz"))
    maximum = Point(*(max(getattr(point, axis) for point in points) for axis in "xyz"))
    return GCodeProgram(path or Path("<memory>"), tuple(commands), tuple(segments), Bounds(minimum, maximum))


def validate_nonnegative_work_xy(program: GCodeProgram, tolerance: float = 0.001) -> None:
    """Reject a program that crosses the lower-left work-XY boundary.

    The parser expands I/J arcs into their swept points before calculating
    bounds, so this check covers arc extrema as well as ordinary segment
    endpoints.  Negative Z remains valid because cutting below work Z0 is a
    separate, intentional operation.
    """
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Work-coordinate tolerance must be finite and nonnegative")
    minimum = program.bounds.minimum
    if minimum.x < -tolerance or minimum.y < -tolerance:
        axis = "X" if minimum.x < -tolerance else "Y"
        value = minimum.x if axis == "X" else minimum.y
        raise GCodeError(
            f"Program crosses negative work {axis} at {value:.6f} mm; "
            "all work X/Y coordinates must be nonnegative"
        )
    for index, segment in enumerate(program.segments, start=1):
        for point in (segment.start, segment.end):
            if point.x < -tolerance or point.y < -tolerance:
                axis = "X" if point.x < -tolerance else "Y"
                value = point.x if axis == "X" else point.y
                raise GCodeError(
                    f"Segment {index} crosses negative work {axis} at {value:.6f} mm; "
                    "all work X/Y coordinates must be nonnegative"
                )


def _target(current: float, values: list[float] | None, absolute: bool) -> float:
    if not values:
        return current
    value = values[-1]
    return value if absolute else current + value


def _arc_points(
    start: Point,
    end: Point,
    words: dict[str, list[float]],
    *,
    clockwise: bool,
    line_number: int,
) -> list[Point]:
    center_x = start.x + words.get("I", [0.0])[-1]
    center_y = start.y + words.get("J", [0.0])[-1]
    radius_start = math.hypot(start.x - center_x, start.y - center_y)
    radius_end = math.hypot(end.x - center_x, end.y - center_y)
    if radius_start <= 0 or not math.isclose(radius_start, radius_end, rel_tol=0.002, abs_tol=0.01):
        raise GCodeError(f"line {line_number}: invalid I/J arc geometry")

    start_angle = math.atan2(start.y - center_y, start.x - center_x)
    end_angle = math.atan2(end.y - center_y, end.x - center_x)
    sweep = end_angle - start_angle
    if clockwise:
        if sweep >= 0:
            sweep -= math.tau
    elif sweep <= 0:
        sweep += math.tau
    if math.isclose(start.x, end.x, abs_tol=1e-9) and math.isclose(start.y, end.y, abs_tol=1e-9):
        sweep = -math.tau if clockwise else math.tau

    steps = max(8, math.ceil(abs(sweep) / math.radians(5)))
    ratios = {index / steps for index in range(steps + 1)}
    # Sampling at a fixed angular interval can skip a cardinal point by a
    # small amount.  Add the exact circle extrema so bounds and safety checks
    # cover the complete arc sweep, not just its endpoints and samples.
    for cardinal in (0.0, math.pi / 2, math.pi, -math.pi / 2):
        if sweep > 0:
            delta = (cardinal - start_angle) % math.tau
            if delta <= sweep + 1e-12:
                ratios.add(max(0.0, min(1.0, delta / sweep)))
        else:
            delta = (start_angle - cardinal) % math.tau
            if delta <= -sweep + 1e-12:
                ratios.add(max(0.0, min(1.0, delta / (-sweep))))
    result = [start]
    for ratio in sorted(ratios):
        if ratio <= 1e-12:
            continue
        angle = start_angle + sweep * ratio
        result.append(
            Point(
                center_x + radius_start * math.cos(angle),
                center_y + radius_start * math.sin(angle),
                start.z + (end.z - start.z) * ratio,
            )
        )
    result[-1] = end
    return result
