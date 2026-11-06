# Coordination

This folder is the lightweight control plane for backlog work. Keep it current,
brief, and useful to the next person. Detailed requirements and durable technical
evidence may live elsewhere; link to them rather than copying them here.

## Files

- [`BACKLOG.md`](BACKLOG.md) is the authoritative queue and task state.
- [`STATUS.md`](STATUS.md) is the at-a-glance snapshot of active work, blockers,
  and the next planning action.
- [`HANDOFFS.md`](HANDOFFS.md) is the append-only channel for completion and
  verification messages.

## Task lifecycle

`ready` → `in-progress` → `implemented` → `done`

Use `blocked` from any state when progress needs a decision or external change.
Only the planning agent adds, splits, reprioritizes, signs off, or closes tasks.
`implemented` means the execution agent completed the scoped work and recorded
verification, but planning sign-off is still pending. A verifier may accept the
evidence or return the task to `in-progress`; only planning sign-off moves it to
`done`.

## Execution runs

The planner should authorize a bounded run in `STATUS.md` by listing its task IDs
and review checkpoint. The run should normally contain several related tasks or a
whole milestone, not one tiny ticket.

An execution agent owns one current task at a time but owns permission to proceed
through the whole run. It must keep working while an eligible task remains:

1. Claim the next `ready` task whose dependencies are `done` or provisionally
   `implemented` within the same run.
2. Implement, test, and record exact evidence. Mark it `implemented`.
3. Immediately claim the next eligible task. Do not wait merely because a planner
   or verifier has not yet responded.
4. If one task is blocked, record it and continue with another independent task in
   the run when that work is safe and will not create conflicting assumptions.
5. Stop at the stated checkpoint, when no eligible task remains, or when continuing
   would cross an authorization, safety, architecture, or destructive-action
   boundary. A failing test is something to diagnose and repair, not automatically
   a reason to stop.

The execution agent may make routine repairs, update tests/docs, and refine small
implementation details needed to satisfy the authorized outcomes. It must escalate
scope changes that alter safety policy, public compatibility, hardware authority,
or the agreed architecture.

## Working agreement

1. Read `AGENTS.md`, `STATUS.md`, and every item in the authorized run.
2. Put your agent/run name in the Active section and claim the current backlog row
   before editing.
3. Stay within that row's scope. Record newly discovered work as a handoff note;
   the planner decides whether it becomes a task.
4. Do not have overlapping writers. If ownership is unclear, stop and leave the
   task unclaimed.
5. At each task boundary, update the row/status and append a handoff with exact
   verification commands and results—never just “tests pass”—then continue.
6. Self-verification is required for progress. Independent verification is still
   preferred for final sign-off, but its availability must not stall the run.
7. When stopping, leave the working tree in a reviewable state and summarize the
   entire run, unresolved findings, and the precise next action.

Task IDs are stable and sequential: `C-001`, `C-002`, and so on. Keep backlog
descriptions outcome-based; put implementation detail in linked documents or the
handoff entry.

## Maintenance

- Update `STATUS.md` whenever run scope, current ownership, blockers, checkpoint,
  or the next action changes.
- Keep completed rows in `BACKLOG.md`; periodically move older completed rows to
  a dated archive only if the file becomes hard to scan.
- Append to `HANDOFFS.md`; correct mistakes with a later note rather than rewriting
  another agent's evidence.
