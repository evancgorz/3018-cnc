"""Unit checks and mask render for the separate C-095 wider-ray helper."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from shapely.geometry import Point, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))
from ttc3018_control.ornament_cam import OrnamentSettings, raster_region, _polygons
from tapered_rays import make_tapered_ray_layout, clip_rays_to_sky

C091 = ROOT / "artifacts/ornaments/hawkeye/two-bit/c091-approved-raised-plane"


def sky_zone_from_c095():
    settings = OrnamentSettings(**json.loads((C091 / "report.json").read_text())["settings"])
    original, _ = raster_region(C091 / "approved-depth-mask.png", settings)
    inner = Point(55, 55).buffer(32.0, quad_segs=256)
    aircraft = unary_union([
        p for p in _polygons(inner.difference(original))
        if p.area > 15 and p.intersects(box(30, 44, 80, 66))
    ])
    return inner.intersection(box(20, 66, 90, 91)).difference(aircraft.buffer(.15))


def cross_section_width(poly, line, fraction):
    (ax, ay), (bx, by) = line.coords
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    x, y = ax + fraction * dx, ay + fraction * dy
    nx, ny = -dy / length, dx / length
    probe = __import__("shapely.geometry", fromlist=["LineString"]).LineString(
        ((x - nx * 10, y - ny * 10), (x + nx * 10, y + ny * 10))
    )
    intersection = poly.intersection(probe)
    return intersection.length


def verify():
    angles = (30, 45, 60, 75, 90, 105, 120, 135, 150)
    layout = make_tapered_ray_layout(angles_deg=angles)
    assert len(layout.centerlines) == len(layout.polygons) == 9
    sky = sky_zone_from_c095()
    # Match C-095 final clipping, including the 1.2 mm inset from the sky-zone edge.
    clip_zone = sky.intersection(Point(55, 55).buffer(30.8, quad_segs=256))
    clipped = clip_rays_to_sky(layout, clip_zone)
    assert clipped.difference(clip_zone).area < 1e-10, "clipped ray mask escapes the C-095 sky/aircraft/inset mask"
    for idx, (angle, line, poly) in enumerate(zip(angles, layout.centerlines, layout.polygons)):
        (x0, y0), (x1, y1) = line.coords
        expected = (
            (55 + 11 * math.cos(math.radians(angle)), 62 + 11 * math.sin(math.radians(angle))),
            (55 + 27 * math.cos(math.radians(angle)), 62 + 27 * math.sin(math.radians(angle))),
        )
        assert math.dist((x0, y0), expected[0]) < 1e-10
        assert math.dist((x1, y1), expected[1]) < 1e-10
        assert cross_section_width(poly, line, .02) == __import__('pytest').approx(.8 + (3.3-.8)*.02, abs=1e-9)
        assert cross_section_width(poly, line, .98) == __import__('pytest').approx(.8 + (3.3-.8)*.98, abs=1e-9)
        assert clipped.intersection(line).length > 0, f"ray {idx} centerline was entirely clipped"
    return layout, clip_zone, clipped


def render_mask(geometry, sky_zone, out_path):
    size, extent = 1100, 110.0
    image = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(image)
    def pixels(geom, fill):
        polys = [geom] if geom.geom_type == "Polygon" else [g for g in getattr(geom, "geoms", ()) if g.geom_type == "Polygon"]
        for p in polys:
            coords = [(x/extent*size, (extent-y)/extent*size) for x,y in p.exterior.coords]
            draw.polygon(coords, fill=fill)
            for ring in p.interiors:
                draw.polygon([(x/extent*size, (extent-y)/extent*size) for x,y in ring.coords], fill="white")
    pixels(sky_zone, (220, 223, 226))
    pixels(geometry, (48, 159, 151))
    image.save(out_path)


if __name__ == "__main__":
    rays, sky, clipped = verify()
    output = HERE / "widened-ray-mask.png"
    render_mask(clipped, sky, output)
    print(json.dumps({
        "result": "passed",
        "rays": len(rays.centerlines),
        "angles_deg": [30,45,60,75,90,105,120,135,150],
        "center_mm": [55,62],
        "radii_mm": [11,27],
        "widths_mm": [0.8,3.3],
        "clipped_ray_area_mm2": round(clipped.area, 5),
        "mask": str(output),
    }, indent=2))




