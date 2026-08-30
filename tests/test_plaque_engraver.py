import pytest

from ttc3018_control.gcode import parse_gcode
from ttc3018_control.plaque_engraver import BORDER_STYLES, generate_plaque_gcode


@pytest.mark.parametrize("border", BORDER_STYLES)
def test_every_border_generates_a_parser_accepted_program_inside_plaque(border: str) -> None:
    engraving = generate_plaque_gcode("HELLO", "WORLD", border=border, width=100, height=50, margin=5)
    program = parse_gcode(engraving.gcode)
    assert program.bounds.minimum.x >= 0
    assert program.bounds.minimum.y >= 0
    assert program.bounds.maximum.x <= 100
    assert program.bounds.maximum.y <= 50
    assert engraving.stroke_count > 2


def test_plaque_can_start_spindle_explicitly() -> None:
    engraving = generate_plaque_gcode("HELLO", spindle_rpm=1200)
    assert "M3 S1200" in engraving.gcode


def test_text_stays_clear_of_the_border_line() -> None:
    engraving = generate_plaque_gcode("TITLE", "SUBTITLE", width=100, height=50, margin=5)
    # The first stroke is the border. All remaining text strokes must be inside it.
    text_points = [point for stroke in engraving.strokes[1:] for point in stroke]
    assert min(x for x, _y in text_points) > 5
    assert max(x for x, _y in text_points) < 95
    assert min(y for _x, y in text_points) > 5
    assert max(y for _x, y in text_points) < 45


def test_disabled_subtitle_is_ignored_and_centers_the_title() -> None:
    engraving = generate_plaque_gcode("TITLE", "IGNORED", subtitle_enabled=False, width=100, height=50, margin=5)
    title_points = [point for stroke in engraving.strokes[1:] for point in stroke]
    assert min(y for _x, y in title_points) == pytest.approx((50 - 10) / 2)
    assert max(y for _x, y in title_points) == pytest.approx((50 + 10) / 2)


@pytest.mark.parametrize("kwargs", ({"width": 10, "title_height": 20}, {"margin": 40}, {"border": "Nope"}))
def test_plaque_rejects_invalid_or_nonfitting_layout(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        generate_plaque_gcode("HELLO", **kwargs)
