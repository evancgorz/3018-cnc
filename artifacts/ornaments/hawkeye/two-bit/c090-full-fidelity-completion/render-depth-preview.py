"""Render an approval preview for the C-084 broad + C-090 fine sequence."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from shapely.affinity import scale
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
C084_DIR = ROOT / "artifacts" / "ornaments" / "hawkeye" / "two-bit" / "c084-runtime-45m"
C084 = C084_DIR / "01-detail-c084-broad-only-008-review-only.nc"
C090 = HERE / "02-detail-c090-fine-residual-completion-review-only.nc"
OUTPUT = HERE / "c090-plane-emphasis-depth-preview.svg"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def geometry_path(geometry) -> str:
    polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
    paths = []
    for polygon in polygons:
        for ring in (polygon.exterior, *polygon.interiors):
            paths.append("M " + " L ".join(f"{x:.4f} {y:.4f}" for x, y in ring.coords) + " Z")
    return " ".join(paths)


def hawkeye_plane_emphasis():
    """Broad silhouette beneath the existing shallow Hawkeye line-art."""
    # Fill only the recognisable side-view fuselage, radar dome and tail.  The
    # wings, props and other fine outlines stay shallow so they do not turn
    # into an invented geometric blob.
    fuselage = Polygon(((16.5, 52.2), (20.5, 51.0), (36.0, 50.8), (45.0, 51.2),
                        (55.0, 51.4), (67.0, 52.0), (79.0, 52.5), (85.2, 53.3),
                        (85.5, 54.7), (81.0, 55.5), (67.0, 56.2), (53.0, 56.5),
                        (41.0, 56.5), (20.5, 56.2), (16.5, 55.2)))
    tail = Polygon(((74.5, 55.6), (77.0, 61.0), (79.4, 61.3), (79.0, 55.8)))
    radome = scale(Point(47.5, 59.0).buffer(2.2, quad_segs=32), xfact=2.6, yfact=0.36)
    return unary_union((fuselage, tail, radome))


def main() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    c084 = load_module(C084_DIR / "prepare-c084-broad-only.py", "depth_preview_c084")
    c069 = c084.load_module(c084.SOURCE_DIR / "prepare-c069-flow.py", "depth_preview_c069")
    generator = c069.load_module(c069.SOURCE_SCRIPT, "depth_preview_generator").load_generator()
    with generator.Image.open(generator.SOURCE) as image:
        image_size = image.size
    settings = generator.settings_for(image_size)
    approved, _ = generator.raster_region(generator.SOURCE, settings)
    approved = approved.difference(Point(*generator.HOLE_CENTER).buffer(generator.HOLE_KEEPOUT_RADIUS, quad_segs=256))
    broad = generator.emitted_paths_by_depth(C084.read_text(encoding="ascii"))[-generator.TARGET_DEPTH]
    fine = generator.emitted_paths_by_depth(C090.read_text(encoding="ascii"))[-generator.FINE_DEPTH]
    broad_sweep = generator.swept(broad, settings.effective_diameter)
    fine_settings = generator.settings_for(image_size, depth=generator.FINE_DEPTH,
                                           stepover=generator.FINE_STEPOVER,
                                           stepdown=generator.FINE_DEPTH)
    fine_sweep = generator.swept(fine, fine_settings.effective_diameter)
    plane = hawkeye_plane_emphasis().intersection(Point(55, 55).buffer(45, quad_segs=256))
    deep = broad_sweep.union(plane)
    untouched = approved.difference(deep.union(fine_sweep))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="110mm" height="140mm" viewBox="0 0 110 140">
<title>Hawkeye ornament plane-emphasis depth approval preview</title>
<desc>Proposed review rendering, not a stock simulation. Brown cuts reach 1.625 mm and expose the second plywood ply; the Hawkeye silhouette is intentionally deep. Gold cuts are 0.04 mm fine surface detail.</desc>
<rect width="110" height="140" fill="#f7f0df"/>
<g transform="translate(0 110) scale(1 -1)">
<circle cx="55" cy="55" r="50" fill="#ead7b1" stroke="#3b3026" stroke-width="0.45"/>
<path d="{geometry_path(approved)}" fill="#f5e8cf" fill-rule="evenodd"/>
<path d="{geometry_path(deep)}" fill="#774126" fill-rule="evenodd"/>
<path d="{geometry_path(fine_sweep)}" fill="#e3b54e" fill-rule="evenodd"/>
<path d="{geometry_path(untouched)}" fill="#d86b5c" fill-rule="evenodd" opacity="0.8"/>
<circle cx="55" cy="100" r="3" fill="none" stroke="#bf3131" stroke-width="0.25"/>
</g>
<g font-family="sans-serif" font-size="3" fill="#2d241e">
  <text x="5" y="116">Proposed approval preview — Hawkeye, 100 mm ornament</text>
  <rect x="6" y="120" width="4" height="4" fill="#774126"/><text x="12" y="123.2">Deep: −1.625 mm · plane / second ply</text>
  <rect x="6" y="126" width="4" height="4" fill="#e3b54e"/><text x="12" y="129.2">Fine: −0.040 mm · surface detail</text>
  <rect x="6" y="132" width="4" height="4" fill="#d86b5c"/><text x="12" y="135.2">Unreachable at specified cutter/depth</text>
</g></svg>'''
    OUTPUT.write_text(svg, encoding="utf-8", newline="\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
