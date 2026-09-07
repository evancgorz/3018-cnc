"""Generate Pine's deterministic 2.5D STEP showcase fixtures."""

from pathlib import Path

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def write_step(name: str, shape) -> None:
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    status = writer.Write(str(EXAMPLES / name))
    if status != 1:
        raise RuntimeError(f"Could not write {name}: STEP status {status}")


def mounting_plate():
    shape = BRepPrimAPI_MakeBox(40, 28, 4).Shape()
    for x, y in ((5, 5), (35, 5), (5, 23), (35, 23)):
        axis = gp_Ax2(gp_Pnt(x, y, -1), gp_Dir(0, 0, 1))
        cutter = BRepPrimAPI_MakeCylinder(axis, 2.1, 6).Shape()
        shape = BRepAlgoAPI_Cut(shape, cutter).Shape()
    slot = BRepPrimAPI_MakeBox(gp_Pnt(13, 11, -1), 14, 6, 6).Shape()
    return BRepAlgoAPI_Cut(shape, slot).Shape()


def pocket_with_island():
    base = BRepPrimAPI_MakeBox(40, 30, 5).Shape()
    pocket = BRepPrimAPI_MakeBox(gp_Pnt(5, 5, 2), 30, 20, 4).Shape()
    shape = BRepAlgoAPI_Cut(base, pocket).Shape()
    island = BRepPrimAPI_MakeBox(gp_Pnt(16, 12, 2), 8, 6, 3).Shape()
    return BRepAlgoAPI_Fuse(shape, island).Shape()


def stepped_pockets():
    shape = BRepPrimAPI_MakeBox(42, 28, 6).Shape()
    shallow = BRepPrimAPI_MakeBox(gp_Pnt(4, 5, 4), 10, 18, 3).Shape()
    deep = BRepPrimAPI_MakeBox(gp_Pnt(17, 5, 2), 10, 18, 5).Shape()
    axis = gp_Ax2(gp_Pnt(35, 14, 3), gp_Dir(0, 0, 1))
    round_pocket = BRepPrimAPI_MakeCylinder(axis, 4.5, 4).Shape()
    for cutter in (shallow, deep, round_pocket):
        shape = BRepAlgoAPI_Cut(shape, cutter).Shape()
    return shape


def raised_boss_panel():
    shape = BRepPrimAPI_MakeBox(40, 28, 4).Shape()
    axis = gp_Ax2(gp_Pnt(11, 14, 4), gp_Dir(0, 0, 1))
    round_boss = BRepPrimAPI_MakeCylinder(axis, 5, 2).Shape()
    rectangular_boss = BRepPrimAPI_MakeBox(gp_Pnt(24, 9, 4), 10, 10, 2).Shape()
    for boss in (round_boss, rectangular_boss):
        shape = BRepAlgoAPI_Fuse(shape, boss).Shape()
    return shape


def profile_with_hole():
    polygon = BRepBuilderAPI_MakePolygon()
    for x, y in ((0, 6), (6, 0), (34, 0), (40, 6), (40, 19), (34, 25), (6, 25), (0, 19)):
        polygon.Add(gp_Pnt(x, y, 0))
    polygon.Close()
    face = BRepBuilderAPI_MakeFace(polygon.Wire()).Face()
    shape = BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, 4)).Shape()
    axis = gp_Ax2(gp_Pnt(7, 12.5, -1), gp_Dir(0, 0, 1))
    hole = BRepPrimAPI_MakeCylinder(axis, 2.5, 6).Shape()
    return BRepAlgoAPI_Cut(shape, hole).Shape()


def _cylinder(x: float, y: float, radius: float, bottom: float, height: float):
    axis = gp_Ax2(gp_Pnt(x, y, bottom), gp_Dir(0, 0, 1))
    return BRepPrimAPI_MakeCylinder(axis, radius, height).Shape()


def _obround(x: float, y: float, length: float, width: float, bottom: float, height: float):
    """Return a horizontal obround with its lower-left bounding corner at x/y."""
    radius = width / 2
    middle = BRepPrimAPI_MakeBox(
        gp_Pnt(x + radius, y, bottom), length - width, width, height
    ).Shape()
    left = _cylinder(x + radius, y + radius, radius, bottom, height)
    right = _cylinder(x + length - radius, y + radius, radius, bottom, height)
    return BRepAlgoAPI_Fuse(BRepAlgoAPI_Fuse(middle, left).Shape(), right).Shape()


def _xz_prism(points: tuple[tuple[float, float], ...], y: float, depth: float):
    """Extrude an X/Z polygon along Y for a deterministic ramp cutter."""
    polygon = BRepBuilderAPI_MakePolygon()
    for x, z in points:
        polygon.Add(gp_Pnt(x, y, z))
    polygon.Close()
    face = BRepBuilderAPI_MakeFace(polygon.Wire()).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, depth, 0)).Shape()


def nested_relief():
    """Nested pocket -> island -> pocket topology plus a through hole."""
    shape = BRepPrimAPI_MakeBox(42, 30, 6).Shape()
    shallow = BRepPrimAPI_MakeBox(gp_Pnt(4, 4, 3), 34, 22, 4).Shape()
    shape = BRepAlgoAPI_Cut(shape, shallow).Shape()
    island = BRepPrimAPI_MakeBox(gp_Pnt(15, 10, 3), 12, 10, 3).Shape()
    shape = BRepAlgoAPI_Fuse(shape, island).Shape()
    island_recess = BRepPrimAPI_MakeBox(gp_Pnt(18, 13, 4.25), 6, 4, 3).Shape()
    shape = BRepAlgoAPI_Cut(shape, island_recess).Shape()
    return BRepAlgoAPI_Cut(shape, _cylinder(34, 7, 2.2, -1, 8)).Shape()


def ramp_and_features():
    """A planar ramp/terrace combined with a pocket and through holes."""
    shape = BRepPrimAPI_MakeBox(42, 28, 6).Shape()
    ramp_cutter = _xz_prism(
        ((10, 5.2), (24, 2.0), (24, 7.0), (10, 7.0)),
        6,
        16,
    )
    shape = BRepAlgoAPI_Cut(shape, ramp_cutter).Shape()
    pocket = BRepPrimAPI_MakeBox(gp_Pnt(27, 7, 4.0), 9, 8, 3).Shape()
    shape = BRepAlgoAPI_Cut(shape, pocket).Shape()
    for x, y in ((5, 5), (36, 23)):
        shape = BRepAlgoAPI_Cut(shape, _cylinder(x, y, 2.1, -1, 8)).Shape()
    return shape


def mixed_feature_plate():
    """Dense but reachable mixed feature test for wall-first clearing."""
    shape = BRepPrimAPI_MakeBox(44, 30, 5).Shape()
    shallow = BRepPrimAPI_MakeBox(gp_Pnt(4, 5, 3.5), 10, 18, 3).Shape()
    deep = BRepPrimAPI_MakeBox(gp_Pnt(18, 5, 1.5), 10, 18, 4).Shape()
    for cutter in (shallow, deep):
        shape = BRepAlgoAPI_Cut(shape, cutter).Shape()
    boss = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(35, 20, 5), gp_Dir(0, 0, 1)), 3.8, 1
    ).Shape()
    shape = BRepAlgoAPI_Fuse(shape, boss).Shape()
    slot = _obround(5, 11, 13, 5, -1, 8)
    shape = BRepAlgoAPI_Cut(shape, slot).Shape()
    for x, y in ((36, 6), (36, 26)):
        shape = BRepAlgoAPI_Cut(shape, _cylinder(x, y, 2.0, -1, 8)).Shape()
    return shape


def two_part_nest():
    """Two disconnected solids, each with an internal through feature."""
    left = BRepPrimAPI_MakeBox(18, 20, 5).Shape()
    left = BRepAlgoAPI_Cut(left, _cylinder(11, 10, 2.4, -1, 7)).Shape()
    right = BRepPrimAPI_MakeBox(gp_Pnt(24, 5, 0), 18, 20, 5).Shape()
    right = BRepAlgoAPI_Cut(right, _obround(26, 12, 9, 4.5, -1, 7)).Shape()
    return BRepAlgoAPI_Fuse(left, right).Shape()


def main() -> None:
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    examples = {
        "showcase-mounting-plate.step": mounting_plate(),
        "showcase-pocket-island.step": pocket_with_island(),
        "showcase-stepped-pockets.step": stepped_pockets(),
        "showcase-raised-bosses.step": raised_boss_panel(),
        "showcase-profile-hole.step": profile_with_hole(),
        "cusp-nested-relief.step": nested_relief(),
        "cusp-ramp-and-features.step": ramp_and_features(),
        "cusp-mixed-feature-plate.step": mixed_feature_plate(),
        "cusp-two-part-nest.step": two_part_nest(),
    }
    for name, shape in examples.items():
        write_step(name, shape)
        print(name)


if __name__ == "__main__":
    main()
