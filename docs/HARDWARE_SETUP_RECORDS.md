Portable hardware setup records
=============================

A setup record describes stock, tool geometry, and a fixture datum. It does not read or write Pine machine-profile, fixture, work-zero, recovery, or controller state. Copy the setup directory with a project or point agents at it.

Every measured or reported field carries a value, unit, provenance kind, and optional note. Provenance kinds are measured, user-reported, assumed, and unknown. Unknown facts use a null value. A setup can retain its stock and tool while its machine-coordinate fixture offsets stay unknown.

List or inspect setup files without attaching to Pine:

    .\.venv\Scripts\python.exe -m ttc3018_control.hardware_setups list examples\hardware-setups
    .\.venv\Scripts\python.exe -m ttc3018_control.hardware_setups inspect examples\hardware-setups plywood-vbit-engraving

SetupRegistry exposes list(), load(setup_id), describe(setup_id), and cam_defaults(setup_id, kind, settings). Direct-file consumers can use load_setup(path), list_setups(directory), and resolve_cam_defaults(record, kind, settings). CAM defaults only reuse values with recorded provenance and reject disagreement with design values. They never infer cut depth, feeds, clearance, spindle command, fixture coordinates, raster margin, or operation strategy. Unknown facts remain unresolved.


To reuse a record in CAM, add a setup reference relative to the design file.
The [plaque example](../examples/agent-cam/plaque-saved-setup.json) uses the
sample plywood and V-bit record. Supply operation-specific choices such as
depth and any feeds or clearances absent from the record.

Both the synchronous command and the background worker resolve the named
record into settings and snapshot its provenance in the generated bundle.
Rebuilding from the bundle's design uses its embedded snapshot. Pine shows
the reported setup in Machine and Job, and flags a different selected machine
profile when the record names one. Verify the stock, installed tool, fixture,
and datum at the machine as part of the ordinary preflight.
