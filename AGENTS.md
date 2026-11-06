# Agent instructions

- Favor a straightforward operator experience. Avoid redundant confirmations,
  arbitrary expiry, and blocks that do not address a concrete failure. When an
  operation is blocked, explain the actual reason and the action that resolves it.
  Keep machine-state and motion checks proportionate to the real risk, and make
  routine recovery and reuse of saved settings easy.

- If any TTC 3018 application instance is running, treat it as user-owned and do not terminate, restart, activate, focus, resize, capture, or interact with it unless the user gives explicit permission in the current request. Explicit permission authorizes only the stated observation or interaction scope; do not terminate or restart the instance unless the user separately authorizes that action.
- Make source and test changes without disturbing a running instance. Do not relaunch the app after changes; tell the user that a manual relaunch is required to load them.
- For requests that turn an idea, image, or drawing into a CNC design or job, follow `.github/skills/design-to-cnc/SKILL.md`. Keep design iteration, tool-aware preview, explicit design approval, and CAM/job generation in the agent workflow; use Pine for machine/workpiece setup, job review and preflight, and guarded machine operation.

## Coordination

- Read `coordination/README.md` before planning or executing backlog work.
- Treat `coordination/BACKLOG.md` as the task queue and `coordination/STATUS.md` as the current snapshot.
- Before editing, claim the authorized execution run and its current task in both files. Do not work on a task owned by another agent.
- An execution agent should continue through all unblocked tasks in its authorized run; completing one task is not a reason to stop or wait for review.
- After each task, append evidence to `coordination/HANDOFFS.md`, update the queue/status, and immediately claim the next eligible task. Stop only at the run checkpoint, a genuine blocker, an unsafe/unauthorized boundary, or when no eligible work remains.
- Planning review and sign-off close the run. Independent verification may happen during execution but should not idle the execution agent when other authorized work is available.

## CNC job preparation

- Start with the executable design-to-job command and backend CLI quickstart in
  [the CNC workflow](docs/AGENT_CNC_JOB_WORKFLOW.md). The working design specs
  are in [examples/agent-cam](examples/agent-cam/).
- For agent-generated or optimized CNC jobs, use the reusable prompt templates and artifact checklist in [`docs/AGENT_CNC_JOB_WORKFLOW.md`](docs/AGENT_CNC_JOB_WORKFLOW.md). Keep generation offline and candidates review-only unless the current request explicitly authorizes the specific physical operation.
