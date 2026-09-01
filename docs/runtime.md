# Runtime and reporting

The runtime consumes a negotiated `Plan` as an immutable input. It executes
ready actions sequentially by action identifier, adds only constraints declared
by successful actions, and never asks a driver to propose more work.

## Failure semantics

Independent ready actions continue after a failure. An action whose required
constraint was not produced ends as `blocked`; it is never attempted. Every
action therefore reaches one final state:

- `succeeded`;
- `failed`;
- `blocked`.

The event stream also records `planned`, `ready`, and `running` transitions.
Command attempts retain their exit code, standard output, standard error,
summary, and structured driver details.

For interactive text execution, the CLI subscribes to that event stream. It
flushes the command heading and frozen-plan summary before invoking the first
action, then flushes `running` and terminal action states immediately. The
persisted report is still assembled from the completed `RunResult`; streaming
does not change event ordering or the canonical machine-readable document.
Quiet mode suppresses intermediate output, while JSON, YAML, and XML remain a
single undecorated document.

## Local action adapter

An action with a command is executed directly from the workspace with UTF-8
capture. `${POLY_RUN_DIRECTORY}` placeholders in arguments and action-specific
environment variables resolve to the run directory. A command-less action is
delegated to the registered driver's `ActionHandler`; the executor treats both
paths identically.

## Canonical report

`poly.report/v1` distinguishes four levels:

- installed verbs;
- applicable actions proposed for the current inventory and selection;
- actions retained in the frozen plan;
- actions currently ready or completed in a run.

Text, JSON, YAML, and XML renderers receive the same canonical document. The
machine formats retain the entire inventory, diagnostics, rejected candidates,
plan, commands, constraints, results, logs, and events. The text renderer
presents the same information as a compact operator report.

## Persistence

Initialized workspaces persist the latest inventory under `.poly/state` and
plan/run reports under `.poly/runs/<plan-id>`. Files use the
`poly.state/v1` envelope around the canonical report. Reads migrate legacy v0
envelopes and raw v1 reports atomically. `poly report <plan-id>` prefers the run
result when present and otherwise renders the saved plan.
