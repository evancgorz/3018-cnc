import pytest

from ttc3018_control.gcode import parse_gcode
from ttc3018_control.text_engraver import FONT_NAMES, generate_text_gcode


def test_generates_metric_centerline_gcode_accepted_by_job_parser() -> None:
    engraving = generate_text_gcode(
        "HI",
        text_height=10,
        depth=-0.4,
        safe_z=4,
        cut_feed=250,
        plunge_feed=80,
    )
    program = parse_gcode(engraving.gcode)
    assert engraving.width == pytest.approx(14.2)
    assert engraving.height == 10
    assert engraving.stroke_count == 6
    assert program.bounds.minimum.z == -0.4
    assert program.bounds.maximum.z == 4
    assert "M3" not in engraving.gcode


def test_optional_spindle_start_is_explicit() -> None:
    engraving = generate_text_gcode("A", spindle_rpm=1200)
    assert "M3 S1200\n" in engraving.gcode
    assert engraving.gcode.index("M3 S1200") < engraving.gcode.index("G0 Z3")


def test_manual_spindle_is_not_stopped_at_program_start() -> None:
    engraving = generate_text_gcode("A")
    commands = [line for line in engraving.gcode.splitlines() if line and not line.startswith(";")]
    assert commands[:5] == ["G21", "G17", "G90", "G94", "G0 Z3"]
    assert commands[-2:] == ["M5", "M2"]


def test_multiline_center_alignment_uses_positive_coordinates() -> None:
    engraving = generate_text_gcode("A\nHI", alignment="Center", text_height=5)
    program = parse_gcode(engraving.gcode)
    assert engraving.height == pytest.approx(12)
    assert program.bounds.minimum.x >= 0
    assert program.bounds.maximum.x <= engraving.width + 0.001


def test_font_styles_generate_distinct_paths() -> None:
    simple = generate_text_gcode("S", font="Simple")
    rounded = generate_text_gcode("S", font="Rounded")
    technical = generate_text_gcode("S", font="Technical")
    assert simple.gcode != rounded.gcode
    assert simple.width != technical.width


@pytest.mark.parametrize("font", ("Italic", "Script", "Playful", "Cursive"))
def test_extra_fonts_generate_previewable_strokes(font: str) -> None:
    engraving = generate_text_gcode("HI", font=font)
    assert font in FONT_NAMES
    assert engraving.strokes
    assert all(len(stroke) >= 2 for stroke in engraving.strokes)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"text_height": 0.1},
        {"depth": 0},
        {"safe_z": 0},
        {"cut_feed": 0},
        {"font": "Comic Sans"},
    ],
)
def test_rejects_unsafe_or_invalid_parameters(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        generate_text_gcode("TEST", **kwargs)


def test_rejects_unsupported_character() -> None:
    with pytest.raises(ValueError, match="not supported"):
        generate_text_gcode("EMAIL@HOME")
