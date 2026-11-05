# Agent instructions

- If any TTC 3018 application instance is running, treat it as user-owned and do not terminate, restart, activate, focus, resize, capture, or interact with it unless the user gives explicit permission in the current request. Explicit permission authorizes only the stated observation or interaction scope; do not terminate or restart the instance unless the user separately authorizes that action.
- Make source and test changes without disturbing a running instance. Do not relaunch the app after changes; tell the user that a manual relaunch is required to load them.
- For requests that turn an idea, image, or drawing into a CNC design or job, follow `.github/skills/design-to-cnc/SKILL.md`. Keep design iteration, tool-aware preview, explicit design approval, and CAM/job generation in the agent workflow; use Pine for machine/workpiece setup, job review and preflight, and guarded machine operation.
