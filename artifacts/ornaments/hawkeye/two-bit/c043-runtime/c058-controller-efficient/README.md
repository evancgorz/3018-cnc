# C-058 controller-efficient engraving candidate

The prior physical run was aborted after the machine crawled through pixel-scale
stair steps. The source program's median cutting segment was 0.0718 mm and most
junctions were right-angle or sharper, so GRBL had to decelerate at nearly every
image pixel even though the programmed feed was 450 mm/min.

`prepare-controller-efficient.py` replaces a raster chord only when the full
effective V-bit disk for that stage remains inside the approved black artwork,
outside the hanger keepout and inside the stock. It retains the same three deep
passes (Z-0.6, -1.2 and -1.625 mm), shallow Z-0.04 detail pass, F450 cutting,
F120 plunging and S1000 spindle command.

The checked candidate reduces XY cutting segments from 158,857 to 88,676
(44.18%), doubles the median segment from 0.0718 to 0.1435 mm and reduces
90-degree-or-sharper junctions from 121,605 to 75,136. The first broad boundary,
where the operator stopped the old run, is reduced much more aggressively by the
0.08 mm broad tolerance. The shallow detail uses a tighter 0.04 mm tolerance.

Exact full-diameter cutter sweeps increase approved-black omission by 7.18 mm2
over the C-057 source (23.60 mm2 total versus 16.43 mm2 before). The generator
rejects candidates over 10 mm2 additional omission or under 40% segment
reduction. This remains an offline review artifact until independently verified
and deliberately loaded; generation performs no machine or GUI interaction.

The file retains 22 isolated plunge-only dots per broad pass. Each is encoded as
a same-coordinate G1 after the plunge so cutter-sweep verification includes the
stationary V-bit disk. These 66 lines cause no XY motion and are excluded from
the nonzero segment statistics.

Reproduce with:

```powershell
.\.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c043-runtime\c058-controller-efficient\prepare-controller-efficient.py
```
