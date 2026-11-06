# Pine CNC agent entry points

Read [AGENTS.md](../AGENTS.md) first.

- For “design”, “slice”, “CAM”, or “prepare a CNC job”, follow the
  [offline workflow](../docs/AGENT_CNC_JOB_WORKFLOW.md#run-the-workflow).
  Copy a spec from [examples/agent-cam](../examples/agent-cam/) and run
  `.\.venv\Scripts\python.exe -m ttc3018_control.agent_cam <design.json> <new-output-dir>`
  from the checkout root. Use supplied machining facts. Review the exact
  G-code, report and cutter sweep. Preparation is offline.
- Use [Pine's CLI or Python backend client](../docs/AGENT_CNC_JOB_WORKFLOW.md#backend-api-and-cli)
  for authorized backend interactions. Discover commands offline with
  `.\.venv\Scripts\python.exe -m ttc3018_control.backend.cli --help`.
  Pass the running backend's exact application data directory to `--root`.
  The CLI attaches to the existing backend.
- Loading changes the backend's current job. Treat it separately from offline
  CAM, and keep start and machine motion within the user's explicit scope.
