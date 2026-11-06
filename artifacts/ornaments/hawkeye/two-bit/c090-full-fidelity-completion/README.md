# C-090 full-fidelity completion after C-084 broad engraving

This offline review bundle restores the shallow, fine residual engraving omitted
by the active C-084 broad-only run. It is the required second operation for the
approved Hawkeye design; the coarse broad pass alone is not a final ornament.

Use only after the exact C-084 0.08 mm broad pass has completed with the same
30°/0.1 mm V-bit and unchanged 110 mm-stock / 100 mm-ornament work frame.
It contains only the residual pass at Z−0.0400 mm, so it does not recut the
deep broad engraving.

The exact file is `02-detail-c090-fine-residual-completion-review-only.nc`,
SHA-256 `fabf3a2dfb077c9c8c58cc914a34a20c3c7859176f5dd6ca0adbc73093a83a99`.
It contains 85,494 commands with a 46.26-minute nominal feed-based estimate.
That number excludes acceleration, GRBL corner limits, streaming, setup, and
material effects; it is not a physical ETA.

Combined with C-084 0.08 mm broad engraving, its full-cutter sweep retains the
same intended full-detail treatment as C-069: 23.74 mm² (0.985%) of approved
black area is inaccessible to the specified V-bit at the assigned depths. The
combined sweep is contained within the approved artwork and outside the hanger
keepout. This is the known cutter-resolution limit, not an intentional
broad-only simplification.

Regenerate and verify offline:

```powershell
.\.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c090-full-fidelity-completion\prepare-c090-fine-completion.py
```

No machine job was loaded, started, stopped, or otherwise changed.
