# Backlog

This is the authoritative execution queue. Priority is `P0` (urgent) through `P3`
(eventual). Dependencies are task IDs or `—`. Owner is `—` when unclaimed.
`implemented` satisfies a dependency provisionally inside the same authorized run;
`done` means the planning agent reviewed and signed off the result.

| ID | Pri | State | Owner | Outcome | Depends on | Detail |
| --- | --- | --- | --- | --- | --- | --- |
| C-001 | P0 | implemented | codex-execution | Prove all ViewModel storage and discovery are isolated in tests | — | [Batch A](../docs/LUNA_XHIGH_IMPROVEMENT_BACKLOG.md#batch-a--make-isolated-testing-a-provable-property) |
| C-002 | P0 | implemented | codex-execution | Bind run authorization to current reviewed job and safety evidence | C-001 | [Batch B](../docs/LUNA_XHIGH_IMPROVEMENT_BACKLOG.md#batch-b--close-authorization-and-evidence-gaps) |
| C-003 | P1 | implemented | codex-execution | Complete the minimal operator journey and recovery behavior | C-002 | [Batch C](../docs/LUNA_XHIGH_IMPROVEMENT_BACKLOG.md#batch-c--make-the-minimal-operator-journey-complete) |
| C-004 | P1 | implemented | codex-execution | Make configuration saves and probing flows deterministic | C-001, C-002 | [Batch D](../docs/LUNA_XHIGH_IMPROVEMENT_BACKLOG.md#batch-d--make-configuration-and-probing-predictable) |
| C-005 | P1 | implemented | codex-execution | Prove the full operator journey against the digital twin | C-002, C-003, C-004 | [Batch E](../docs/LUNA_XHIGH_IMPROVEMENT_BACKLOG.md#batch-e--prove-the-operator-journey-against-the-twin) |
| C-006 | P2 | implemented | codex-execution | Perform targeted maintainability and documentation cleanup | C-005 | [Batch F](../docs/LUNA_XHIGH_IMPROVEMENT_BACKLOG.md#batch-f--maintainability-after-correctness) |
| C-007 | P0 | implemented | codex-execution | Audit the in-flight headless backend against the separation contract below | C-001, C-002 | [Separation initiative](#backendfrontend-separation-initiative) |
| C-008 | P0 | implemented | codex-execution | Make the versioned backend API the complete, stable owner of machine behavior | C-007 | [API boundary](#c-008--complete-api-boundary) |
| C-009 | P0 | implemented | codex-execution | Make backend lifetime independent from every frontend client | C-008 | [Process lifetime](#c-009--independent-process-lifetime) |
| C-010 | P1 | implemented | codex-execution | Make the desktop GUI a disposable, reconnectable backend client | C-008, C-009 | [Frontend client](#c-010--restartable-frontend-client) |
| C-011 | P1 | implemented | codex-execution | Provide a guarded agent/CLI interface for headless development and commissioning | C-008, C-009 | [Agent interface](#c-011--agent-facing-interface) |
| C-012 | P1 | implemented | codex-execution | Prove upgrade, disconnect, crash, and relaunch behavior end to end | C-010, C-011 | [Separation acceptance](#c-012--separation-acceptance) |
| C-013 | P0 | blocked | codex-execution | Integrate and commission an independently observable physical E-stop | C-008, C-009, C-011, C-012 | [Physical E-stop](#c-013--physical-e-stop-integration) |
| C-014 | P0 | implemented | codex-execution | Replace manual-reference and close-time return behavior with guarded homing | C-003, C-008, C-009, C-010 | [Homing-first reference](#c-014--homing-first-reference-and-close-flow) |
| C-015 | P0 | in-progress | codex-execution | Simplify the shell around an auto-connected, unified Machine workspace | C-014 | [Unified Machine UX](#c-015--unified-machine-workspace-and-automatic-connection) |
| C-016 | P1 | done | codex-ornament-planning | Audit ornament capability gaps and define a bounded implementation backlog | — | [Ornament plan](../docs/ORNAMENT_CAM_PLAN.md) |
| C-017 | P1 | done | codex-ornament-cam | Add offline, depth-limited ornament CAM export with review evidence | — | [Ornament plan](../docs/ORNAMENT_CAM_PLAN.md) |
| C-018 | P1 | ready | — | Store a reproducible ornament project with measured tool and stock inputs | C-017 | [Ornament plan](../docs/ORNAMENT_CAM_PLAN.md) |
| C-019 | P1 | ready | — | Verify physical-size artwork, minimum features and hanger wood reserve | C-018 | [Ornament plan](../docs/ORNAMENT_CAM_PLAN.md) |
| C-020 | P1 | ready | — | Export aligned engraving and tabbed disc/hole programs with shared XY | C-018, C-019 | [Ornament plan](../docs/ORNAMENT_CAM_PLAN.md) |
| C-021 | P2 | ready | — | Guide backend-owned manual tool changes with renewed Z trust and authorization | C-020 | [Ornament plan](../docs/ORNAMENT_CAM_PLAN.md) |
| C-022 | P2 | ready | — | Add artwork preparation and cutter-sweep review to Prepare/Review | C-020 | [Ornament plan](../docs/ORNAMENT_CAM_PLAN.md) |
| C-023 | P1 | blocked | — | Validate scrap coupon then ornament after separate physical-test authorization | C-020 | [Ornament plan](../docs/ORNAMENT_CAM_PLAN.md) |
| C-024 | P1 | done | codex-ornament-optimization | Reduce unnecessary engraving air moves with verified in-region links and benchmark unchanged artwork | C-017 | [Ornament plan](../docs/ORNAMENT_CAM_PLAN.md) |
| C-025 | P1 | implemented | codex-wifi-bootstrap | Restrict USB to Wi-Fi bootstrap and verify handoff before operation | — | User request 2026-11-01; evidence in HANDOFFS.md |
| C-026 | P1 | done | codex-wifi-bootstrap | Check Windows backend owner liveness without sending process signals | — | Full-suite ownership-test interruption found during C-025 |
| C-027 | P1 | done | codex-z-probe-completion | Confirm Z-probe success, retract in place, require puck removal, then guarded descent to work Z0 | C-025 | User-approved straight-up retract workflow; docs/Z_TOUCH_PLATE.md |
| C-028 | P1 | done | codex-confirmation-cleanup | Bind confirmations to meaningful changes and remove misleading expiry churn | — | User request 2026-11-01 |
| C-029 | P0 | done | codex-jog-deadman | Stop held jogs on lost release/heartbeat and move precision controls inside rose | — | User-reported stuck jog requiring E-stop |
| C-030 | P1 | done | codex-one-bit-slice | Restart app and assess single-bit draft (single-bit slicing withdrawn by user) | C-027, C-028, C-029 | User restart-and-slice request; 100 mm/3 mm/assumed3.175mm cutter |
| C-031 | P1 | done | codex-two-bit-slice | Prepare aligned V-bit detail and endmill hole/cutout review files | C-027, C-028, C-029 | User restored two-tool design; no cutting authorized |
| C-032 | P1 | blocked | codex-probe-diagnosis | Diagnose and correct unnecessary touch probe blocking | — | User request; source and read-only diagnosis |
| C-033 | P1 | done | codex-zero-recall | Persist and recall previous work zero | — | User request; repeatable jigs |
| C-034 | P1 | ready | codex-detail-optimization | Improve ornament detail fidelity and runtime | C-031 | Offline artifacts |
| C-035 | P1 | done | codex-primary | Simplify agent instructions | — | User request |
| C-036 | P0 | done | codex-probe-confirmation | Fix probe confirmation and completion state mismatch | — | User reported stale prompt and confusing probe behavior |
| C-037 | P0 | done | codex-xy-persistence | Persist separately confirmed X/Y machine-relative work zero | — | User request; no motion |
| C-038 | P1 | done | codex-primary | Record actual 30-degree engraving tool and invalidate mismatched draft | — | User-supplied bit specification |
| C-039 | P1 | ready | codex-vbit-detail | Regenerate and verify engraving for 30-degree 0.1 mm V-bit | C-038 | Offline artifact; user preparing machine |
| C-040 | P0 | done | codex-stale-status | Diagnose and fix stale controller status | — | User requests restart after repair |
| C-041 | P0 | done | codex-probe-availability | Remove circular work-zero prerequisite from Z probing | — | User reported Probe Z disabled |
| C-042 | P1 | implemented | codex-workflow-audit | Replace misleading workflow blockers with actionable guidance | — | User request; review Home and primary controls |
| C-043 | P1 | done | codex-fast-engrave | Optimize and verify 30-degree engraving for job readiness | C-039 | User-authorized first-job preparation, no start |
| C-044 | P1 | blocked | codex-probe-popup | Diagnose missing probe-removal prompt | — | User removed puck; no motion authorized |
| C-045 | P1 | done | codex-cutout-thickness | Update cutout draft for measured 3.25 mm stock | — | User caliper measurement |
| C-046 | P0 | implemented | codex-primary | Correct engraving program terminal commands and assess GUI freshness | C-043 | User authorized start, no motion until checks pass |
| C-047 | P0 | implemented | codex-gui-freshness | Show backend-loaded large job in Pine | — | User reports GUI no loaded job |
| C-048 | P0 | implemented | codex-stream-review | Require fresh spindle-off before streaming starts | — | Preserve lifecycle terminal M5 |
| C-049 | P0 | done | codex-connection-failure | Diagnose run communication failure | — | User requests reconnect and retry |
| C-050 | P1 | done | codex-double-feed | Prepare 2x feed engraving candidate | — | User request; retain depth pending input |
| C-051 | P1 | done | codex-restore-detail | Add fine artwork pass to deep engraving test | C-050 | User request, no start |
| C-052 | P1 | done | codex-speed-candidate | Prepare and verify faster engraving candidate | C-051 | User requested 2–3x faster; no machine start |
| C-053 | P1 | done | codex-feed-diagnosis | Diagnose actual speed and buffering on interrupted run | — | User reports motion slower than stated |
| C-054 | P1 | implemented | codex-path-speed | Reduce small-move bottleneck while preserving engraving | C-051 | User reports actual feed far below commanded |
| C-055 | P1 | done | codex-stream-throughput | Improve small-segment streaming throughput | C-053 | User reports actual feed slow; offline tests |
| C-056 | P0 | done | codex-primary | Validate optimized cutter sweep and prepare correct job | C-054 | Coverage report radius/diameter discrepancy |
| C-057 | P1 | done | codex-path-speed | Reduce fine-pass microsegments with verified cutter sweep | C-056 | Improve observed slow motion |
| C-058 | P0 | implemented | codex-primary | Replace jumpy microsegmented ornament motion with a geometry-verified controller-efficient toolpath | C-057 | Offline replacement independently verified; physical throughput still requires a deliberate new run |
| C-059 | P1 | done | codex-guidance | Make agent-guided CNC preparation reproducible and efficient | — | Guidance reviewed; docs/AGENT_CNC_JOB_WORKFLOW.md |
| C-060 | P1 | done | codex-primary | Improve visibility and usability of agent-prepared jobs in the app | — | Honest missing-preview, envelope and runtime labels; focused tests passed |
| C-061 | P1 | done | codex-preview | Provide scalable and honest large-job preview | — | Full suite 894 passed |
| C-062 | P1 | done | codex-provenance | Show useful verified job setup and provenance | — | Full suite 894 passed |
| C-063 | P1 | done | codex-jobstate | Separate prior run outcome from newly loaded job | — | Full suite 894 passed |
| C-064 | P1 | done | codex-primary | Improve usable run-time estimates and reusable agent tooling | — | Full suite 894 passed |
| C-065 | P1 | done | codex-jobstate | Resolve guided rail selection regression identified by Qt shell test | — | Stale fixture corrected |
| C-066 | P1 | done | codex-jobstate | Correct stale saved-zero UI regression fixture | — | Intentional wording reflected in fixture |
| C-067 | P1 | done | codex-preview | Correct simulation limit-control polarity and its regression coverage | — | NC and NO twin tests passed |
| C-068 | P1 | done | codex-jobstate | Update twin guided-journey tests to current direct navigation and homing workflow | — | Review acknowledgement step mismatch also fixed |
| C-069 | P0 | in-progress | codex-primary | Improve observed cutting feed and run the revised ornament | C-058 | User authorizes home, saved zero and start; fixture clear |
| C-070 | P0 | implemented | codex-primary | Add hash-bound accepted-command recovery records for UI and agents | C-063 | User request; source/tests only, did not interrupt active job; accepted lines are explicitly not physical resume positions |
| C-071 | P0 | implemented | codex-primary | Make active-job plot and timing genuinely live and useful | C-061, C-064 | User request; source/tests only, did not interrupt running job |
| C-072 | P0 | implemented | codex-recovery-state-machine | Add automatic controller-loss stop/reconnect recovery with continue/cancel | C-070 | Bounded saved-Wi-Fi retries, M5 acknowledgement, fresh Idle/0 gate, explicit homing/cancel actions; 64 focused tests passed |
| C-073 | P0 | implemented | codex-pause-bookmark | Persist confirmed pause and conservative continuation context | C-070 | Fresh Hold confirmation, exact program/tool context, review-only recovery fences; 145 focused tests passed |
| C-074 | P1 | implemented | codex-primary | Correct active-job plot transform and publish current-layer mapping | C-071 | Overlay now converts the raster painted rect into canvas-local coordinates exactly once |
| C-075 | P1 | implemented | codex-cam-order-metrics | Optimize CAM path order and publish motion-release metrics | C-058 | User requests fewer jumps and better future workflow |
| C-076 | P0 | implemented | codex-reset-auto-home | Automatically guarded-home after positively detected controller reset | C-072 | Reset banner triggers saved-Wi-Fi reconnect, M5 acknowledgement, fresh Idle/0 gate, then guarded home; silence retains explicit Continue/Cancel |
| C-078 | P0 | implemented | codex-primary | Prepare newest verified Hawkeye CAM profile for offline restart review | C-075 | Validated and selected C-069 flow: 100 mm frame, 30° 0.1 mm V-bit, SHA f38e959b…; user-authorized fresh execution started from persisted zero |
| C-077 | P0 | implemented | codex-primary | Align the live cutter marker and execution path with the displayed toolpath | C-071, C-074 | Overlay now matches both frontend PreserveAspectFit and backend source-raster letterboxing; focused preview test passed; GUI reloaded |
| C-079 | P0 | implemented | codex-pause-revision | Make Pause immune to telemetry revision races | C-073 | Dispatcher treats pause-job as stop intent: ignores stale revisions/idempotency replay and permits it through the motion safety gate; focused regression test passed (5 tests) |
| C-080 | P1 | implemented | codex-layer-visibility | Add Run-view visibility toggles for current layer, cutting paths, and rapid paths | C-071, C-077 | Run page now has three independent checkboxes; backend large previews split into aligned cut/rapid rasters, small jobs expose categorized vectors. 8 focused tests passed; no restart or machine interaction |
| C-081 | P0 | implemented | codex-watchdog-autorecover | Make controller-silence recovery issue spindle-stop, reconnect, guarded-home, and clear continuation guidance automatically | C-072, C-076 | Silence recovery auto-homes only after reconnect, M5 acknowledgement, and fresh Idle/0 RPM; bounded retries repeat M5 after lost ACK/status; never resumes a job automatically |
| C-082 | P0 | implemented | codex-status-payload | Keep backend status snapshots below the bounded protocol size after path-layer preview additions | C-080 | Client now decodes success/error responses using the 1 MiB response cap rather than 256 KiB request cap; regression test passes (11 API tests) |
| C-083 | P0 | implemented | codex-safe-continuation | Generate and verify a safe C-069 continuation after the user-selected command region 4,000 | C-078 | Review-only artifact starts at source command 4063 after completing the prior stroke and retracting; exact suffix, parser, bounds, depth, modal, and rapid-clearance checks pass |
| C-084 | P0 | implemented | /root/runtime_cam | Reduce Hawkeye engraving emitted-motion workload toward the aspirational 45-minute goal | C-078, C-083 | Offline-only linked broad-pass candidates and exact tradeoff evidence in `artifacts/ornaments/hawkeye/two-bit/c084-runtime-45m/README.md`; actual time remains uncalibrated |
| C-085 | P0 | implemented | codex-runtime-diagnostics | Analyze controller throughput and estimate model against observed run telemetry | C-084 | Prefix timing shows ~4.8–5.1× idealized slowdown; physical telemetry and source analysis point to short blocks, sharp junctions, and retracts rather than a simple sender bottleneck; see HANDOFFS |
| C-086 | P0 | implemented | /root/performance_workflow | Make future CNC CAM preparation performance-aware by default | C-084, C-085 | Analyzer reports short-block/junction/retract rates and conservative profile-matched runtime projections; optional target comparison is informational and never blocks execution; workflow docs updated; 3 focused tests pass |
| C-087 | P0 | implemented | codex-hybrid-pocket | Evaluate a fast hybrid engraving strategy using the existing 1/8 in endmill for broad deep pocketing and the 0.1 mm V-bit only where needed | C-084, C-085 | Infeasible at nominal 3.175 mm: conservative source-art inset is empty; no endmill file emitted. Evidence in artifacts/ornaments/hawkeye/two-bit/c087-hybrid-pocket/ |
| C-088 | P1 | in-progress | codex-primary | Produce a general, review-only fidelity/runtime ladder by progressively coarsening the fine residual pass | C-084, C-086 | Preserve the full broad pass and enumerate exact tool-sweep, command, junction, retract and estimate tradeoffs rather than only broad-only versus full-detail extremes |
| C-089 | P0 | implemented | codex-primary | Add and compare localized adaptive concentric engraving regions for Hawkeye | C-084, C-086 | Offline-only C-089 candidate completes localized regions with verified concentric offsets and comparable exact G-code/report evidence; no running job interaction |
| C-090 | P0 | implemented | codex-primary | Prepare the aligned full-fidelity fine-residual completion for the active C-084 broad pass | C-084 | Offline-only fine-residual companion restores the approved detail after C-084; exact combined sweep/coverage and source/output hashes recorded; no live job interaction |
| C-091 | P0 | implemented | /root/approved_design_geometry | Convert approved raised-aircraft concept into verified offline full-detail depth CAM | C-089 | Approved concept threshold geometry, local concentric broad clearing plus fine residual; exact file verification and preview complete; primary owns physical execution |
| C-092 | P0 | implemented | /root/recovery_home_completion | Complete watchdog recovery after verified homing | C-081 | Newer fresh Idle/spindle0 plus trusted reference ends recovery; 9 focused tests passed; primary owns activation and continuation |
| C-094 | P0 | implemented | /root/auto_continuation_implementation | Automatically continue opted-in jobs after verified loss recovery | C-092 | Source/tests only; per-job CLI/API opt-in, conservative replay boundary, verified saved-zero return and bounded3 attempts; primary owns activation |

| C-095 | P1 | implemented | /root | Revise rays/water and render actual V-bit surface geometry for design review | C-091 | Wider tapered rays, rebuilt lettering, modeled emitted paths and strict-row water finish; offline user review required |
| C-096 | P1 | implemented | /root | Ship a repeatable concept-to-CAM workflow and discoverable agent backend entry point | — | Offline bundle and API quickstart; verify before review |
| C-097 | P1 | done | /root | Define the machine-first Pine and background CAM backlog | — | Product direction and execution checkpoints |
| C-098 | P1 | done | /root | Define the Machine and Job journeys and record what earlier runs already proved | — | A |
| C-099 | P1 | done | /root | Standardize portable projects, review bundles, and retained cut records | C-098 | A |
| C-100 | P1 | done | /root | Open agent review bundles through the existing guarded job loader | C-099 | A |
| C-101 | P1 | done | /root/audit | Make the active backend data directory discoverable without guessing the launch directory | C-098 | A |
| C-102 | P1 | done | /root | Make routine setup and saved work-zero reuse easy to follow in Machine | C-098 | B |
| C-103 | P1 | done | /root | Combine job open, review, preflight, and run in one Job workspace | C-100, C-102 | B |
| C-104 | P1 | done | /root | Make pause, abort, reconnect, and continuation understandable in the Job workspace | C-103 | B |
| C-105 | P1 | done | /root/cam_worker | Give agents a complete offline route from brief and saved inputs to a review bundle | C-099 | C |
| C-106 | P1 | done | /root/fidelity | Let agents compare faster toolpaths against an explicit fidelity target | C-105 | C |
| C-107 | P1 | done | /root | Validate ordered multi-tool bundles with a shared XY frame and tool-specific setup | C-100, C-105 | C |
| C-108 | P1 | done | /root/parity | Verify equivalent job handoffs and guarded operation across GUI, CLI, and simulation | C-104, C-106, C-107 | D |
| C-109 | P2 | done | /root | Move CAM authoring out of primary desktop navigation after replacement workflows pass | C-108 | D |
| C-110 | P2 | in-progress | /root | Organize the repo around product code, project inputs, generated runs, and retained cut records | C-099, C-109 | D |
| C-111 | P2 | in-progress | /root/audit | Provide a reversible migration for local machine state outside the checkout | C-101 | D |
| C-112 | P2 | ready | — | Publish and verify the operator, agent, and contributor start paths | C-110, C-111 | D |
| C-113 | P1 | done | /root | Remove mandatory delegation from repo agent instructions | — | User request |
| C-114 | P1 | done | /root/cam_worker | Add portable named stock, cutter, and fixture setup records | — | E |
| C-115 | P1 | done | /root | Resolve and snapshot named setup records for offline CAM and review | C-114 | E |
| C-116 | P1 | done | /root | Make saved setup assumptions visible at Machine and Job handoff | C-100, C-102, C-115 | E |

Future hardware and machine-expansion work remains in
[`docs/CNC_PLATFORM_BACKLOG.md`](../docs/CNC_PLATFORM_BACKLOG.md). It should be
promoted into this queue only when the planner defines a bounded, authorized task.


## Machine-first Pine and background CAM

Pine's desktop centers on two workspaces. **Machine** handles physical setup
and recovery. **Job** handles opening, checking, and running an exact file.
Agents prepare and compare CAM candidates offline. The persistent backend
remains the authority for machine state, checks, and motion. A project records
design intent, a candidate records a particular toolpath and its assumptions,
and the setup records what is true at the machine today.

### A. Agree on the handoff and make it work

- **C-098** — Use the existing C-096 example bundles and Hawkeye evidence to
  document both journeys. Inventory existing GUI actions and classify them as
  Machine, Job, expert utility, or offline CAM. Capture current setup steps,
  repeated input, and handoff gaps as a baseline for C-108.
- **C-099** — Specify relative source paths, versioned metadata, exact G-code
  hashes, units, origin, tool, stock, preview, and assumptions. Separate draft
  outputs from retained exact files and review evidence for approved or run
  jobs. Preserve historical Hawkeye references. Publish a small replayable
  example and compatibility rules for existing C-096 bundles.
- **C-100** — Open a bundle from GUI and CLI, resolve its program safely, verify
  its hash, and feed the same validated job loader as plain G-code. Show the
  expected setup and verification evidence alongside the parsed preview.
  Handle incomplete, changed, or unsupported bundles with actionable errors.
  Bundle metadata supplies context. The backend verifies actual machine facts.
- **C-101** — Define consistent GUI, CLI, and Python-client discovery and an
  explicit override for isolated development. Handle ambiguous or missing roots
  clearly and verify single ownership with temporary roots. Preserve the
  current launch behavior until the migration in C-111.

### B. Simplify the operator journey

- **C-102** — Put connection, guarded homing, jog, probing, saved XY/Z, and
  recovery in Machine. Distinguish saved values from trusted current state.
  Reuse facts that remain valid and explain the shortest next action when a
  gate fails. Check first setup, repeat setup, and recovery in simulation.
- **C-103** — Carry one job identity, preview, and relevant setup facts from
  open through preflight and execution. Keep Machine reachable to resolve a
  blocker. Make job replacement and changed setup facts visible. Preserve
  direct G-code loading and accessible keyboard operation.
- **C-104** — Keep pause and abort accessible in the states that need them.
  Show fresh versus stale position, commanded versus observed progress, and
  nominal versus calibrated time. Present the current recovery action and
  existing continuation policy without changing who can authorize motion.

### C. Make offline CAM the normal agent workflow

- **C-105** — Build on C-096. From a brief plus reusable inputs, guide source
  selection, identify missing machining facts, generate and verify the exact
  file, and produce a replayable bundle with provenance. Report progress and
  failures, support retry without overwriting prior candidates, and make
  completion available for operator review. Exercise plaque, raster, and STEP
  paths before expanding to any operation needed for C-109.
- **C-106** — Build on C-084 through C-089 evidence. Compare geometry coverage,
  residual depth or finish where applicable, short moves, junctions, retracts,
  and nominal runtime on the same inputs. Offer candidates under a stated
  fidelity limit. Use physical estimates only with comparable measured runs,
  and keep the exact baseline and candidate files available.
- **C-107** — Model ordered passes with exact files, tools, a common XY frame,
  and required Z and tool checks. Review each pass and preserve the normal
  backend authorization at tool changes. Validate an engraving plus cutout
  example offline and in simulation.

### E. Reuse hardware setup records

- **C-114** — Keep machine configuration and measured zero in existing stores.
  Define portable named records for stock dimensions/material, cutter geometry,
  and a fixture/setup that references them and declares the work datum.
  Provide an offline, validated way for agents to list and inspect records.
- **C-115** — Let a design select a saved setup, reuse matching stock and tool
  fields, and preserve the exact values and record provenance in the review
  bundle. Verify reproducibility after the registry changes and ensure the
  background worker snapshots setup inputs at submission.
- **C-116** — Show the saved setup name, stock, tool, and datum in review.
  Distinguish reported setup assumptions from current machine evidence.
  Where existing live fields support a comparison, explain a mismatch and
  keep normal backend preflight in charge.

### D. Prove the replacement and migrate

- **C-108** — Replay a known Hawkeye-style repeat and a new agent-prepared
  project with isolated state. Compare setup steps and repeated inputs to the
  baseline. Verify plain G-code parity, tampered bundles, changed zero/tool,
  disconnect, pause/abort, and GUI reconnect while a simulated job runs.
  Record any workflow gaps as backlog work before removing desktop CAM.
- **C-109** — For each existing authoring feature, document the equivalent
  offline path or a temporary compatibility route. After parity review, make
  Machine and Job primary and retire replaced CAM UI paths incrementally.
- **C-110** — Keep one Python package and stable CLI entry points. Separate
  reusable CAM, small examples, project inputs, generated runs, and retained
  cut records. Group CAM internals as useful with compatibility for existing
  imports and scripts. Verify packaging, references, and rebuilds before moves.
- **C-111** — Implement and test an explicit external data-root migration on
  copied fixtures. Preserve profiles, saved zeros, recovery state, and backend
  ownership. Verify interrupted migration, legacy discovery, and rollback.
  Any real cutover requires a separately authorized maintenance window.
- **C-112** — Verify documented setup, GUI, offline CAM, backend discovery,
  simulator, and packaging entry points from a clean workspace. Update operator
  and agent instructions and label historical architecture accordingly.

Execution checkpoints are A (portable job handoff), B (operator flow), C
(offline CAM parity and tradeoffs), and D (migration readiness). B and C can
overlap as their dependencies clear. Software and simulation evidence are the
default. Live application interaction and physical checks require the current
request's explicit authorization.


## Adding a task

Add one row with a stable ID, a testable outcome, explicit dependencies, and a
single detail link when more context is needed. A task should be small enough for
one worker and one review cycle.

## Backend/frontend separation initiative

### Goal

Run machine control, safety state, hardware connections, jobs, and durable machine
configuration in a Qt-free backend whose lifetime does not depend on the GUI. The
desktop GUI and automation agents must use the same versioned interface and must
not bypass backend validation. Closing, crashing, or relaunching a frontend must
not disconnect the controller or interrupt active backend work.

This initiative completes and verifies the existing uncommitted `backend/`
implementation. It must not introduce a parallel control path. The backend remains
the sole owner of transports and command ordering; clients express typed operator
intent. Remote/non-loopback access and unattended physical commissioning are not
authorized by this initiative.

### C-007 — Separation contract and gap audit

- Reconcile the current `backend/`, Qt composition, CLI, tests, README, and
  architecture decision record with the actual working tree.
- Inventory every GUI call that still reaches an in-process
  `ApplicationController`, service, transport, configuration store, or safety rule.
- Define authoritative backend state, client-local presentation state, ownership,
  authentication, compatibility, reconnect, lease, and orphaned-operation policy.
- Produce a gap matrix and targeted tests before changing architecture further.
- Acceptance: the reviewer can trace every machine-affecting GUI/CLI action to one
  guarded backend operation and every displayed machine fact to backend state.

### C-008 — Complete API boundary

- Replace compatibility stubs and lossy projections with explicit typed snapshots,
  events, capabilities, commands, structured errors, and confirmation flows.
- Move all hardware discovery, machine configuration, job loading/validation,
  commissioning evidence, and safety decisions behind the backend boundary.
- Specify protocol/schema compatibility and fail closed on incompatible clients;
  expose capabilities so an older or smaller client can degrade honestly.
- Keep raw GRBL and unrestricted command injection unavailable to ordinary clients.
- Acceptance: backend contract tests cover every supported workflow without Qt;
  the GUI contains presentation logic only and cannot bypass a rejected action.

### C-009 — Independent process lifetime

- Give the backend a single-instance, owner-scoped startup/discovery mechanism and
  explicit start, attach, health, and operator-authorized shutdown behavior.
- Define client heartbeats or leases without making GUI presence necessary for an
  active job. A dropped client must not silently pause, abort, or disconnect work.
- Preserve emergency hold/abort access after reconnect; reject unsafe shutdown
  during active operations and clean stale discovery records safely.
- Acceptance: disconnect, GUI close, GUI crash, and client timeout leave backend
  state and transport ownership intact; a new client observes the same session and
  current operation. Backend failure is shown honestly and never auto-restarted
  into hardware motion.

### C-010 — Restartable frontend client

- Make normal desktop startup attach to the backend rather than construct a second
  controller or open hardware. Keep an explicit isolated development mode if needed.
- Separate GUI preferences/layout from backend-owned operational state. Rebuild the
  view entirely from a snapshot plus ordered events after launch or reconnect.
- Handle unavailable, starting, incompatible, reconnecting, and active-job states
  with clear controls; closing the window releases only frontend resources.
- Acceptance: repeatedly relaunch the GUI during idle, jog/hold, probing recovery,
  and job execution without duplicate commands, lost status, transport teardown,
  or a backend restart.

### C-011 — Agent-facing interface

- Provide a documented, scriptable CLI or small Python client over the same public
  contract used by the GUI, including read-only status/capability inspection.
- Model hardware changes as validate → preview/diff → explicit apply → verify, with
  machine identity, expected revision, idempotency, audit events, and rollback or
  safe rejection for partial failures.
- Require explicit authorization for motion, spindle, probing, physical connection,
  commissioning, or shutdown. Agents must not receive a privileged bypass or raw
  transport handle.
- Acceptance: an isolated agent can inspect and test backend behavior without Qt;
  simulated commissioning is fully automatable, while physical actions remain
  capability-gated, attributable, bounded, and separately authorized.

### C-012 — Separation acceptance

- Add end-to-end tests for backend-first and GUI-first startup, multiple observers,
  stale/incompatible clients, duplicate requests, reordered/missed events, backend
  crash, frontend crash, frontend relaunch, and safe backend shutdown.
- Prove active-job continuity and reconstructed UI state using the digital twin;
  verify one command is executed at most once across retries and reconnects.
- Define independent backend/frontend version and packaging expectations, migration
  behavior for durable state, operator diagnostics, and recovery documentation.
- Update the architecture decision record only after observed behavior matches it.
- Acceptance: backend-only and GUI-client suites pass independently, followed by a
  full integration run; evidence records exact processes, sessions, commands,
  event revisions, cleanup, and remaining physical-hardware limitations.

### C-013 — Physical E-stop integration

#### Safety architecture

- Use a maintained, normally-closed, dual-channel emergency-stop circuit and a
  suitably rated safety relay/contactor to remove hazardous spindle and motion
  power independently of all software. The program is never the primary stopping
  mechanism.
- Use isolated auxiliary contacts from that safety circuit for observation. One
  contact may assert the DLC32 `RESET` header, but reset/disconnect alone is only
  secondary evidence: it cannot distinguish an E-stop from controller reboot,
  cable loss, or power loss.
- Feed a separate, normally-closed auxiliary contact into a dedicated, isolated
  digital-input adapter supported by the backend. Do not reuse an axis limit,
  probe, I2C, or undocumented ESP32 pin. Loss of feedback power, broken wiring,
  stale heartbeat, or adapter disconnect must read as unsafe/unknown—not clear.
- Select the actual relay, contact ratings, input adapter, supply, wiring, and
  enclosure only after an electrical review of the machine's spindle, driver, and
  controller power topology. Record exact part numbers and schematic.

#### Backend behavior

- Add a typed safety-input adapter and capability declaration. The persistent
  backend exclusively owns it and publishes `clear`, `active`, `latched`,
  `unknown`, and `fault` with timestamps, session identity, raw channel states,
  debounce evidence, and reason.
- On `active`, disagreement, or loss of trustworthy feedback: latch the software
  E-stop immediately; stop accepting new commands; cancel streaming; request GRBL
  realtime reset/hold and spindle stop only as best-effort secondary actions;
  invalidate machine reference, work zero, run authorization, and commissioning
  trust; retain the event across GUI/agent disconnects and backend restarts.
- Treat a DLC32 disconnect followed by boot/startup output as a controller-reset
  event. Correlate it with the independent input for diagnostics, but never infer
  “E-stop pressed” or “safe” from reset traffic alone.
- Keep status/diagnostics readable while latched. Hold, abort, and power-removal
  guidance remain reachable; all motion, spindle start, probing, homing, job start,
  and configuration actions that could energize hardware fail closed.
- Recovery requires: physical button released; both safety channels agree; input
  is fresh for a defined settling interval; relay reset is performed physically
  where required; controller reconnects into a fresh non-running state; operator
  explicitly acknowledges the event; and the machine is re-homed/re-referenced
  before work zero or motion can be trusted. Never auto-resume a job.

#### Interface and evidence

- Show the same authoritative backend state in GUI and CLI, including whether
  power removal is confirmed, merely commanded, unavailable, or unknown. Never
  display “safe” solely because no alarm is currently reported.
- Write an append-only audit event for transitions, disagreements, adapter loss,
  reset correlation, acknowledgements, and recovery, using monotonic ordering and
  without secrets.
- Unit-test debounce, contact disagreement, broken wire, input-adapter loss,
  backend restart, stale/reordered events, reset without E-stop, E-stop without
  reset feedback, and repeated presses. Use the digital twin and a fake input
  adapter before any physical test.
- Bench acceptance must be separately authorized and performed spindle/tool-free
  with measured continuity and power-removal evidence. Final machine acceptance
  must prove hazardous power drops without software, backend detection remains
  correct with the GUI closed, no command is accepted while latched, and recovery
  never restores position trust or resumes work automatically.

### C-014 — Homing-first reference and close flow

#### Outcome

The installed homing switches become the ordinary way to establish machine
reference. Remove the operator-facing manual `Set/Establish Reference` path and
replace the optional close-time “move to reference” action with an explicit,
guarded home cycle. Closing or restarting the GUI must still never shut down the
persistent backend.

#### Behavior

- Remove the `Set Reference` / `Establish reference` button, guided action, help
  text, and obsolete GUI confirmation route. Do not offer manual position trust as
  a fallback when homing is unavailable or uncommissioned.
- Change workflow projection and recovery guidance to require successful homing
  before work-zero, probing, or jobs. A missing, partial, stale, failed, or
  uncommissioned switch configuration must remain visibly blocked with a direct
  commissioning explanation.
- Replace the close dialog's `Move to reference, then close` action and three-axis
  return sequence with `Home, then close`. This must be an explicit user action,
  route through the backend's guarded typed homing operation, wait for observed
  homing completion/fresh Idle, and close only the frontend. Never home
  automatically merely because a window-close event occurred.
- Retain a clearly labeled close-without-motion path so the GUI cannot trap the
  operator when homing is unsafe or unavailable. It closes frontend resources
  only and does not change backend/controller state.
- Preserve the low-level application reference primitive only where required for
  deterministic simulation/internal tests; it must not remain an ordinary GUI or
  agent action capable of bypassing physical homing policy. Remove it from the
  public backend/CLI action surface if no supported non-physical workflow needs it.
- A home failure, alarm, stale status, E-stop/safety-input block, active job,
  spindle-on state, or disconnect must keep the frontend open and show the backend
  rejection/failure. Never reinterpret a failed home as a trusted reference.

#### Verification and authorized hardware boundary

- Update QML/static tests, workflow tables, ViewModel/backend adapter tests, and
  digital-twin acceptance for successful, rejected, failed, disconnected, and
  close-without-motion paths. Prove exactly one home request, no legacy reference
  UI action, backend session survival, and frontend close only after fresh Idle.
- Software and digital-twin verification should be completed first. The user has
  authorized backend-only hardware testing for this task if it is necessary to
  verify the result. Before restarting an agent-owned backend or sending homing,
  verify through the backend that the machine is connected, Idle, spindle-off,
  and behind all configured safety gates. Do not launch, relaunch, focus, capture,
  or otherwise interact with the GUI.
- Physical evidence must identify the backend session, preflight state, single
  homing request, switch sequence, final fresh Idle, and post-home reference trust.
  Abort physical testing without motion if any prerequisite is unknown. Hardware
  testing is not required to complete the software slice and must not silently
  commission switches or change user configuration.

### C-015 — Unified Machine workspace and automatic connection

#### Navigation and visual design

- Replace the eight blocky workflow tabs with a compact rounded/segmented primary
  navigation containing only `Machine`, `Prepare`, `Review`, and `Run`. Use a
  consistent pill-like radius, spacing, selected-state contrast, keyboard focus,
  and hover/pressed states; retain accessible labels and deterministic tab order.
- Remove Connection, Safety, Reference, Work Zero, and Configure as primary tabs.
  Consolidate connection recovery, contextual safety state, homing, jogging, work
  zero, and supported probing/calibration into the `Machine` workspace.
- Put a clear `Home machine` button directly above the work-zero controls, visually
  grouping homing as their prerequisite. It invokes the same guarded backend
  homing operation and never sends raw commands. Keep its state, completion, and
  rejection reason visible there. Do not place Home inside the jog panel.
- Move `Configure` to a small labeled button in the bottom utility area. Move
  `Console` to a small bottom utility button and retain its expert-mode/guarded
  behavior. Neither utility should compete with the primary workflow navigation.
- Remove the dedicated Safety page, but do not suppress actionable safety facts.
  Show a compact contextual warning/banner in Machine and Run only when a hazard,
  E-stop, stale/unknown safety input, supervision failure, or recovery action
  requires attention. Normal/healthy safety state should not consume a tab.

#### Automatic connection

- Remove the normal `Disconnected`, `Backend ready`, and `Unknown` header pills and
  the prominent Disconnect button. A healthy attached backend and ordinary
  connected state should be quiet; show a compact status only while connecting,
  degraded, blocked, or failed. Keep manual disconnect/reconnect available from a
  secondary connection/recovery menu or dialog, not the primary header.
- Persist the last **successful** physical connection method and endpoint in the
  backend-owned settings. On application startup, after the frontend has attached
  and received a compatible snapshot, automatically try that method first.
- If the first physical attempt fails, try the other configured physical method
  before presenting `Device not found`: saved TCP host/port and the saved or
  currently discovered COM endpoint. If COM discovery returns multiple new ports,
  do not guess; present the chooser after the deterministic saved candidates fail.
  Never scan arbitrary network addresses or connect to an unrecognized endpoint.
- Bound every attempt and cancellation. Do not overlap transports, create a second
  controller, or let frontend restart disturb an already connected backend. If the
  backend is already connected, the frontend simply adopts its current session.
- Do not automatically connect the digital twin merely because it was used last;
  it remains an explicit development choice. Do not open the connection dialog
  until all safe deterministic TCP/COM candidates have failed. The dialog explains
  each attempted method and provides retry/change-endpoint actions.
- Test preferred-TCP and preferred-COM order, fallback success, both-fail popup,
  missing/stale COM, multiple COM choices, timeout/cancel, backend-already-connected,
  frontend relaunch, and no duplicate connect request. All policy and persistence
  live behind the backend boundary; QML only reflects state and intent.

#### Live machine envelope

- Add a live tool/device-position marker to the machine virtual-envelope preview.
  Drive it from the authoritative fresh backend machine coordinates (`MPos`), not
  work coordinates or a frontend prediction. Update it on state/position events.
- Map X/Y consistently into the drawn travel envelope and expose Z through marker
  styling or an adjacent value. Hide or clearly mark the indicator unknown when
  disconnected, status is stale, coordinates are absent, or the backend session
  changes. Never clamp an out-of-envelope coordinate into a falsely safe-looking
  position; show an out-of-bounds warning at the true edge/direction.
- Add deterministic rendering/math tests for origin, corners, midpoint, Y-axis
  orientation, Z display, stale/unknown state, out-of-bounds state, resize, and
  reconnect. A headless Qt test must prove live backend coordinate changes move the
  marker without rebuilding or directly controlling the machine.

#### Acceptance

- At 1180×720 and 1500×920, required Machine controls and bottom utilities remain
  reachable without overlap; rounded navigation has visible selected/focus states.
- No Establish Reference, Connection, Safety, Reference, Work Zero, or Configure
  primary tab remains. Machine contains jog plus a Home-then-work-zero grouping and
  supported probe controls; Prepare/Review/Run remain intact.
- Startup silently reaches an existing backend session or automatically tries the
  bounded saved physical connection sequence. Only complete failure interrupts the
  user. Critical safety/recovery information remains visible when actionable.
- Use temporary roots, fake transports, and the digital twin for implementation
  tests. This task does not authorize GUI interaction or new physical motion;
  optional hardware testing remains governed by C-014 and AGENTS.md.




































