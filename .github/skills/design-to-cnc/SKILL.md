---
name: design-to-cnc
description: Turn an idea, image, or drawing into a tool-aware CNC design and validated job files, with an explicit design-preview approval gate.
---

# Design to CNC

Use this workflow when a user wants to turn an idea, reference image, logo, or
drawing into a CNC-made object. Keep design iteration and CAM in the agent
workflow; use Pine as the machine-facing application for workpiece setup,
validated job review, preflight, monitoring, and guarded execution.

## Required approval gate

Do not generate, export, or present CNC job files as ready to run until the user
has explicitly approved the current design and its tool-aware preview. Approval
applies only to the exact revision shown, including its material, dimensions,
tools, cut depths, and operation order. Any change to those inputs invalidates
approval and requires an updated preview and approval.

## Workflow

1. **Gather requirements.** Identify the finished object's function and
   dimensions, source artwork, desired design edits, stock material and
   thickness, available cutters and their geometry, machine/workholding
   constraints, and output format. Separate confirmed values from assumptions.
   Ask for missing information that could materially affect fit, strength,
   appearance, tool reach, or safe cutting. Never invent feeds, spindle speeds,
   clearances, or machine capabilities; mark unconfirmed process settings for
   operator confirmation.

2. **Inspect the repository's machine/job constraints.** Read the relevant
   repository instructions and documentation, especially Pine's supported
   G-code, machine profile, work-zero, envelope, and preflight requirements.
   Do not assume Pine supports automatic tool changes or arbitrary CAM output.
   Plan one file per tool/setup whenever the controller or application cannot
   safely execute a tool change in-program.

3. **Prepare the design.** Trace or construct clean, closed, dimensioned
   geometry. Preserve the user's explicit visual requirements. Resolve overlaps,
   tiny islands, narrow gaps, and unsupported features against the actual tool
   geometry. Show an editable design draft first; iterate with the user until
   the artwork and layout are right.

4. **Plan machining.** Assign every feature to a specific cutter and operation.
   Calculate reachable feature widths from the cutter geometry and proposed
   depth; for a V-bit, account for the included angle and tip width. Check
   minimum detail, inside corners, clearances, remaining material, stock
   thickness, cut-through depth, holding tabs or other workholding, and the
   machine's usable envelope. Use conservative passes and settings, and clearly
   identify any value that still requires operator confirmation.

5. **Show a tool-aware preview.** Before creating job files, render the actual
   proposed stock removal at the intended scale and depth using the selected
   cutters. Include a legible top view and an oblique/depth view where useful.
   Identify stock dimensions, feature depths, tool assignments, operation order,
   minimum tool-reachable detail, holding features, and any material left
   beneath engravings. The preview must represent the toolpaths being proposed,
   not merely the source artwork. If a credible cut preview cannot be generated,
   explain the limitation and do not imply that an artwork mockup is a machining
   simulation. A geometric render is not a guarantee of surface finish, grain
   behavior, tear-out, rigidity, or successful workholding.

6. **Obtain explicit approval.** Show the preview with its dimensions, material,
   cutters, depths, operation sequence, and unresolved settings. Ask the user
   to approve this exact design and machining plan. Do not generate or export
   job files before an unambiguous approval. If they request revisions, return
   to design or machining planning and show the revised preview.

7. **Generate and validate jobs after approval.** Produce separate, clearly
   named files for each tool/setup when required. Keep a common XY origin and
   document the stock setup, work zero, cutter installation, tool changes,
   re-zeroing needs, and safe order of operations. Validate syntax, units,
   bounds, depths, clearances, tool reach, pass depths, holding features, and
   compatibility with Pine's parser and configured machine envelope. Fail
   closed on unsupported commands, uncertain geometry, or unverified
   assumptions. Do not send jobs to the machine or start motion.

8. **Hand off to the operator.** Provide the approved preview, job files,
   operation/tool checklist, work-zero and setup instructions, and explicit
   validation results and limitations. The operator must load and review each
   job in Pine, confirm the actual stock and machine setup, complete physical
   preflight, and explicitly control job start, pause/resume, or abort. Never
   interact with a running TTC 3018 application unless the user explicitly
   authorizes that specific interaction.

## Worked example: layered plywood ornament

Use this example when continuing the ornament design discussed in this
repository; do not treat it as approval for any newly changed design or job:

- Finished diameter: 100 mm circular ornament.
- Stock: 3.25 mm, three-ply hobby plywood.
- Design edits: use a larger full central sun with 17 evenly spaced,
  equal-length, symmetric black-and-white rays extending toward the inner
  scene border, with the outermost rays horizontal; consolidate water blobs
  into fewer, simpler shapes.
- Fine-detail cutter: Two Trees 1/8-inch V-bit, 3.175 mm cutter diameter, 30°
  included angle, 0.1 mm tip diameter.
- Fill and profile cutter: standard 1/8-inch flat router bit, 3.175 mm diameter.
- Proposed sequence: flat-bit fill engraving, V-bit fine engraving, then use
  the flat router bit to cut the outer ornament profile last. The ornament must
  remain held until all engraving is complete. Use holding tabs or another
  validated workholding method for the final cutout.
- Generate distinct jobs for each tool/setup; do not insert an unsupported
  automatic tool change. Preserve the same stock orientation and XY work origin
  across jobs, and document any required tool re-zeroing.

Confirm actual cutting depths, feeds, spindle speed, passes, tabs, and work
holding with the operator; none are established by the example. Show the
revised ray and simplified-water design in a cut-aware preview before requesting
approval. Approval of the artwork alone is not approval of toolpaths or job
files.
