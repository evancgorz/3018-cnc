# CNC projects

Keep source artwork and models, design specs, and setup references in
`projects/<name>/` or in a separate project directory. Use
`examples/` for small runnable examples and shared test fixtures.
The reusable offline workflow lives in `src/ttc3018_control/cam/`.

Write generated candidates to a new `artifacts/<project>/<run>/` directory.
Git ignores new working outputs. Keep exact approved or executed files,
their reports, and the review decision in the project's retained records
or equivalent durable storage. See the [bundle format](../docs/CNC_REVIEW_BUNDLES.md).

Existing Hawkeye evidence stays at its original paths, as indexed in
[handoffs](../coordination/HANDOFFS.md).
