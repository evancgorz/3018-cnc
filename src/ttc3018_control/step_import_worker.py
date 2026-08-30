"""Short-lived worker used to isolate native OpenCASCADE STEP imports."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from .step_geometry import StepImportError, load_step


def main() -> int:
    if len(sys.argv) != 3:
        print(json.dumps({"error": "STEP importer requires a file path and face orientation"}))
        return 2
    try:
        model = load_step(Path(sys.argv[1]), sys.argv[2])
    except StepImportError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "path": str(model.path),
                "loops": [[[point.x, point.y] for point in loop.points] for loop in model.loops],
                "top_z": model.top_z,
                "thickness": model.thickness,
                "source_bounds": list(model.source_bounds),
                "face_plane": model.face_plane,
                "face_normal": list(model.face_normal),
                "features": [
                    {
                        "kind": feature.kind,
                        "loop_index": feature.loop_index,
                        "depth": feature.depth,
                        "parent_loop_index": feature.parent_loop_index,
                        "is_through": feature.is_through,
                    }
                    for feature in model.features
                ],
                "loop_parents": list(model.loop_parents),
                "surface_patches": [
                    {
                        "loops": [[[point.x, point.y] for point in loop.points] for loop in patch.loops],
                        "a": patch.a,
                        "b": patch.b,
                        "c": patch.c,
                    }
                    for patch in model.surface_patches
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
