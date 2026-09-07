# Pine 2.5D STEP examples

These compact, deterministic models are intended for safe import and CAM
regression tests. Their lower-left model envelope is placed at work `X0 Y0`;
the generated compensated tool envelope must never go negative. Use a 3.175 mm
tool and stock at least as thick as the model when trying them on a 3018.

| File | Approx. envelope | What it exercises | Expected automatic plan |
| --- | --- | --- | --- |
| `cusp-nested-relief.step` | 42 × 30 × 6 mm | nested pocket, island, shallow recess, through hole | detected features, then outer profile |
| `cusp-ramp-and-features.step` | 42 × 28 × 6 mm | sloped planar region plus pocket and through holes | detected features, planar surface, then outer profile |
| `cusp-mixed-feature-plate.step` | 44 × 30 × 6 mm | shallow/deep pockets, raised boss, obround slot, holes | detected features, then outer profile |
| `cusp-two-part-nest.step` | 42 × 25 × 5 mm | two disconnected solids with different internal profiles | per-component feature paths, then outer profile |

The models are deliberately close to the practical 2.5D boundary: planar
faces, pockets, bosses, holes, ramps, and disconnected roots are supported;
undercuts and freeform 3D surfaces are not. The automatic planner machines
internal walls before infill, keeps disconnected regions separate, and leaves
the outside profile until all internal work is complete.

Regenerate the fixtures with `scripts/generate_step_showcase.py`. The generator
uses stable OpenCASCADE boolean construction so the same source geometry can
be used in importer, planner, simulation, and G-code tests.
