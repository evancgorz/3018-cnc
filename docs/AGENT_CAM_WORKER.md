Background offline CAM worker
=============================

The agent CAM worker runs in a detached local process. It receives no backend client and does not read or change machine state. Each submission snapshots its JSON spec and declared source into a new UUID directory. The spec's source path is rewritten to point at that copied file, so later project edits do not alter queued work. Specs are limited to 1 MiB and source files to 64 MiB. At most four active jobs are accepted per run root.

Submit, inspect, cancel, or retry a job from the repository root:

    .\.venv\Scripts\python.exe -m ttc3018_control.cam_worker submit examples\agent-cam\raster.json --root artifacts\cam-runs
    .\.venv\Scripts\python.exe -m ttc3018_control.cam_worker status <job-id> --root artifacts\cam-runs
    .\.venv\Scripts\python.exe -m ttc3018_control.cam_worker cancel <job-id> --root artifacts\cam-runs
    .\.venv\Scripts\python.exe -m ttc3018_control.cam_worker retry <job-id> --root artifacts\cam-runs

State is stored in <root>/jobs/<uuid>/state.json. It includes phase, percentage, failure details, and the final bundle path. A retry gets a new ID and output directory and uses the original input snapshot. A completed bundle appears at <root>/jobs/<uuid>/bundle only after generator verification succeeds and staging is renamed into place. Duplicate submissions cannot overwrite one another. The deadline defaults to 15 minutes and can be changed from 1 to 60 minutes with --timeout.

Cancellation terminates only the isolated CAM generator. Failed or interrupted generation never marks a bundle complete. Partial staging files may remain after an operating-system kill and are not an output bundle. The status reader marks an abandoned job failed when its worker process has ended. Retry from its saved inputs or submit a fresh spec to try again. Inspect completed bundles through the normal Pine review workflow.
