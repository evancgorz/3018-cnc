from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.backend.runtime import BackendRuntime
from ttc3018_control.gcode import Bounds, GCodeProgram, Point, Segment
from ttc3018_control.qt.view_model import ControllerViewModel


def _runtime_for(program: GCodeProgram) -> BackendRuntime:
    runtime = BackendRuntime.__new__(BackendRuntime)
    runtime.application = SimpleNamespace(program=program)
    return runtime


def test_large_preview_renders_last_segment_without_simplifying(tmp_path: Path) -> None:
    a = Point(1.0, 1.0, 0.0)
    b = Point(9.0, 1.0, 0.0)
    corner = Point(9.0, 9.0, 0.0)
    segments = []
    for _ in range(2500):
        segments.append(Segment(a, b, False))
        segments.append(Segment(b, a, False))
    # This final diagonal occupies a part of the image untouched by the first
    # 5,000 moves; truncation or decimation would leave its midpoint blank.
    segments.append(Segment(a, corner, False))
    program = GCodeProgram(
        tmp_path / "large.nc",
        tuple("G1 X1 Y1" for _ in range(5001)),
        tuple(segments),
        Bounds(Point(0, 0, 0), Point(10, 10, 0)),
        1.0,
    )
    runtime = _runtime_for(program)

    detail = runtime._program_snapshot()

    assert detail is not None
    assert detail["commands"] == []
    assert detail["segments"] == []
    assert detail["preview_available"] is True
    preview = detail["preview"]
    assert preview["segment_count"] == 5001
    assert preview["rendered_segment_count"] == 5001
    assert preview["all_segments_rendered"] is True
    assert "narrower than one pixel" in preview["note"]

    encoded = preview["data_url"].split(",", 1)[1]
    image = Image.open(BytesIO(base64.b64decode(encoded))).convert("RGBA")
    # With the square bounds and 1024x768 output, (5, 5) maps to the center.
    assert image.getpixel((512, 384)) == (45, 156, 255, 255)
    assert len(preview["data_url"]) < 700_000

    cached = runtime._program_snapshot()
    assert cached is not None
    assert cached["preview"]["data_url"] == preview["data_url"]


def test_large_preview_separates_cutting_and_rapid_rasters(tmp_path: Path) -> None:
    segments = [
        Segment(Point(1.0, 1.0, 0.0), Point(9.0, 1.0, 0.0), False)
        for _ in range(2501)
    ] + [
        Segment(Point(1.0, 9.0, 3.0), Point(9.0, 9.0, 3.0), True)
        for _ in range(2500)
    ]
    program = GCodeProgram(
        tmp_path / "categorized.nc",
        tuple("G1 X9 Y9" for _ in range(6001)),
        tuple(segments),
        Bounds(Point(0, 0, 0), Point(10, 10, 3)),
        1.0,
    )

    preview = _runtime_for(program)._program_snapshot()["preview"]

    assert preview["path_layers_available"] is True
    assert len(preview["data_url"]) + len(preview["cutting_data_url"]) + len(preview["rapid_data_url"]) < 1_000_000
    cut = Image.open(BytesIO(base64.b64decode(preview["cutting_data_url"].split(",", 1)[1]))).convert("RGBA")
    rapid = Image.open(BytesIO(base64.b64decode(preview["rapid_data_url"].split(",", 1)[1]))).convert("RGBA")

    assert cut.getpixel((512, 682)) == (45, 156, 255, 255)
    assert rapid.getpixel((512, 682))[3] == 0
    assert rapid.getpixel((512, 86)) == (242, 184, 75, 235)
    assert cut.getpixel((512, 86))[3] == 0


def test_small_job_keeps_vector_payload(tmp_path: Path) -> None:
    start = Point(0, 0, 0)
    end = Point(1, 1, 0)
    program = GCodeProgram(
        tmp_path / "small.nc",
        tuple("G1 X1 Y1" for _ in range(5000)),
        tuple(Segment(start, end, False) for _ in range(5000)),
        Bounds(start, end),
        1.0,
    )

    detail = _runtime_for(program)._program_snapshot()

    assert detail is not None
    assert detail["preview_available"] is True
    assert detail["preview"] is None
    assert len(detail["segments"]) == 5000


def test_toolpath_canvas_displays_raster_without_unavailable_notice() -> None:
    qml_path = Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml"
    qml = qml_path.read_text(encoding="utf-8")
    canvas = qml[qml.index("component ToolpathCanvas"):qml.index("Rectangle {\n        visible: window.toastText")]

    assert 'objectName: "largeJobRasterPreview"' in canvas
    assert "appViewModel.preview_image_url" in canvas
    assert "preview_strokes.length === 0 && appViewModel.preview_image_url.length === 0" in canvas
    assert "preview_image_note" in canvas
    assert 'label: "All moves · raster"' in canvas
    # Overlay coordinates must follow both PreserveAspectFit centering and the
    # backend rasterizer's own padded, letterboxed program rectangle.
    assert "rasterForBounds.width - rasterForBounds.paintedWidth" in canvas
    assert "const sourceScale = Math.min" in canvas
    assert "const sourceOffsetX = (sourceW - contentW) / 2" in canvas
    assert 'objectName: "showCurrentLayer"' in qml
    assert 'objectName: "showCuttingPath"' in qml
    assert 'objectName: "showRapidPaths"' in qml
    assert "toolpathCanvas.showCurrentLayer && layer[\"state\"] === \"cutting_layer\"" in canvas
    assert "toolpathCanvas.showCuttingPath" in canvas
    assert "toolpathCanvas.showRapidPaths" in canvas
    assert "preview_cutting_image_url" in canvas
    assert "preview_rapid_image_url" in canvas


def test_view_model_exposes_backend_raster_and_pixel_note(qapp, tmp_path: Path) -> None:
    view_model = ControllerViewModel(ApplicationController(tmp_path))
    data_url = "data:image/png;base64,aGVsbG8="
    view_model.application.program_preview = {
        "data_url": data_url,
        "cutting_data_url": "data:image/png;base64,Y3V0",
        "rapid_data_url": "data:image/png;base64,cmFwaWQ=",
        "path_layers_available": True,
        "note": "Every move projected to 1024 × 768 px.",
    }

    assert view_model._set_backend_program_preview() is True
    assert view_model.preview_image_url == data_url
    assert view_model.preview_cutting_image_url == "data:image/png;base64,Y3V0"
    assert view_model.preview_rapid_image_url == "data:image/png;base64,cmFwaWQ="
    assert view_model.preview_path_layers_available is True
    assert view_model.preview_image_note == "Every move projected to 1024 × 768 px."
    view_model.application.program_preview = {}
    assert view_model._set_backend_program_preview() is False
    assert view_model.preview_image_url == ""
    assert view_model.preview_cutting_image_url == ""
    assert view_model.preview_rapid_image_url == ""
    assert view_model.preview_path_layers_available is False
    view_model.close()


def test_view_model_separates_small_job_cutting_and_rapid_strokes(qapp, tmp_path: Path) -> None:
    cut_start = Point(0, 0, 0)
    cut_end = Point(4, 0, 0)
    rapid_start = Point(4, 0, 3)
    rapid_end = Point(4, 4, 3)
    program = GCodeProgram(
        tmp_path / "small-categories.nc",
        ("G1 X4 F100", "G0 Y4"),
        (Segment(cut_start, cut_end, False), Segment(rapid_start, rapid_end, True)),
        Bounds(Point(0, 0, 0), Point(4, 4, 3)),
        1.0,
    )
    view_model = ControllerViewModel(ApplicationController(tmp_path))

    view_model._set_preview_path_layers(program, has_raster=False)

    assert view_model.preview_path_layers_available is True
    assert view_model.preview_cutting_strokes == [[[0.0, 0.0], [4.0, 0.0]]]
    assert view_model.preview_rapid_strokes == [[[4.0, 0.0], [4.0, 4.0]]]
    view_model.close()
