# Machine and Job journeys

This is the software baseline for the machine-first rollout. The desktop
source currently offers Machine, Prepare, Review, and Run. Existing Hawkeye
artifacts and C-096 test evidence establish the inputs below. Operator timing
and interaction counts remain to be measured in the isolated C-108 replay.

| Journey | Baseline | Target |
| --- | --- | --- |
| Repeat a known cut | Pick the exact retained G-code, identify the fixture and tool from the project record, confirm machine reference and work zero, review, then start. Review and Run are separate workspaces. | Open the retained job in Job. Recall the saved fixture XY through Machine, establish Z as required, and return to the same job preview and checks. |
| New agent-prepared cut | C-096 creates a replayable bundle for plaque, raster or STEP pocket. The desktop file picker loads G-code. The operator separately reads the bundle report for stock, tool and CAM evidence. | Open the bundle directly in Job. Read its evidence beside the parsed preview and resolve only current setup checks before an explicit start. |

| Existing action group | Destination |
| --- | --- |
| Connection, current machine and position, guarded home, jog, probing, saved zero and setup recovery | Machine |
| Open file, preview, job identity, envelope and setup checks, start, progress, pause, abort and continuation | Job |
| Machine profile, commissioning, simulation configuration and console | Expert utilities |
| Plaque and text authoring, STEP preparation and raster slicing, optimization and candidate comparison | Offline CAM, with compatibility paths until parity |

C-096 verified that all three example bundles regenerate byte-for-byte. Hawkeye
C-084 through C-091 show why the original review evidence matters. Nominal time
and full-width coverage can change differently across variants. C-108 should
record repeated input and workspace transitions, verify the source hash shown
at handoff, and exercise a changed tool or zero and a disconnect on the twin.
See [handoffs](../coordination/HANDOFFS.md) and [the roadmap](../coordination/BACKLOG.md#machine-first-pine-and-background-cam).

## Isolated parity evidence

The repeat acceptance builds one representative retained file and opens the
same bytes through CLI and the desktop loader. Reopening adds one file
selection and no CAM regeneration. The new design acceptance builds one
bundle and opens its report directly in Pine, with the same hash and
setup evidence available through the CLI. Neither replay needs re-entry of
CAM settings in Pine. The disconnected machine blocks the start.

Separate tests replay both sequence passes on virtual GRBL, preserve an
active twin job across frontend reconnect, and check recovery, pause and
abort gates. These are software journeys. The replay counts file loads and
settings entries, with physical fixture setup and timing left to the
operator's own work.

## Desktop CAM compatibility

Machine and Job are the primary navigation. CAM tools remains a utility for
existing desktop text, plaque and STEP authoring. New plaque, raster,
shallow STEP pocket and tabbed profile jobs have offline spec examples.
Use the desktop utility for plain text editing and advanced STEP modes
until their offline workflows offer equivalent setup and review.
