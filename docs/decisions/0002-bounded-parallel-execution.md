# ADR 0002: Bound parallel execution by frozen frontiers

- Status: proposed
- Date: 2026-09-02
- Target: Poly 0.13.0

## Context

Poly 0.12.1 executes one ready action at a time. The plan is already finite and
immutable, and constraints already define which actions are ready, but the
runtime has no concurrency contract. In particular, `ActionClaim` represents
planning ownership rather than a runtime lock, controller descriptors expose no
capacity, and legacy in-process handlers capture process-global stdout and
stderr.

Parallel execution must preserve plan identity and deterministic results while
allowing independent actions to overlap safely.

## Decision

### Frozen frontiers

The executor snapshots all ready actions in canonical plan order. That tuple is
one frontier. Constraints produced during the frontier are withheld from
scheduling until every admitted or queued member reaches a terminal state, so a
newly eligible dependant cannot overtake an action that was already ready.

Within a frontier, the scheduler owns admission and event publication. Whenever
a worker becomes free, it scans the remaining tuple in canonical order and
admits the first action that is compatible with the resources currently held.
This is deterministic for a given completion sequence and avoids head-of-line
blocking by an unrelated exclusive resource.

Workers return immutable completion records. A single scheduler thread updates
constraints, assigns the global event sequence, calls the event listener, and
assembles results. Results are emitted in canonical plan order; events preserve
actual admission and scheduler-observed completion order.

### Explicit safety and resources

Driver API 1.1 adds two defaulted action properties:

- `parallel_safe`, default `false`;
- `exclusive_resources`, default empty and normalized as sorted, unique,
  non-empty single-line identifiers.

These properties are execution policy only and are excluded from planning
claims. They are part of the frozen action serialization and therefore affect a
new plan identifier when a driver changes them; the `--jobs` choice never does.

An action with `parallel_safe=false` uses the serial lane and cannot overlap any
other action. `changes_structure=true` always forces that lane. Two parallel-safe
actions overlap only when their exclusive-resource sets are disjoint. API 1.0
drivers remain compatible and their actions receive the conservative defaults.

Each controller descriptor declares `parallel_capacity`, a positive integer
whose backward-compatible default is one. The scheduler enforces both the
global worker limit and one semaphore per selected controller. For one or more
selected controllers, effective global capacity is bounded by the sum of their
declared capacities.

### Worker request

Execution commands accept `--jobs 1`, a positive integer, or `auto`; planning
and action-catalog commands do not. `auto` uses the process CPU affinity when
available, then the logical CPU count, then one. The effective worker limit is
at least one and is the lower of requested process capacity and selected
controller capacity.

### Isolated action context

Every admitted action receives a stable directory below
`<run-directory>/actions/`. Its leaf combines a sanitized action identifier with
a short digest of the original identifier, preventing collisions and path
traversal. `${POLY_RUN_DIRECTORY}` resolves to this action directory while the
workspace remains unchanged.

Commands already return captured process streams and can opt into parallelism.
An opted-in in-process handler writes only through action-scoped output sinks on
`ExecutionContext` or through its structured result. It must not redirect or
mutate process-global stdout or stderr. Existing handlers keep legacy stream
capture and remain on the serial lane.

### Failure and interruption

A failed action publishes no constraints. Its already-running and independent
siblings finish normally; only actions whose requirements remain unavailable
become blocked. Runner exceptions are converted to a failed attempt for their
own action.

Poly 0.13 has one interruption policy, `drain`. The first interrupt stops all
new admissions. Already admitted actions run to completion. Actions that never
started become `cancelled`, the run becomes `interrupted`, and the complete
report is persisted. A second interrupt may terminate the client process but
does not permit Poly to claim that a complete report was persisted. Cooperative
cancellation and forced process or thread preemption are deferred.

## Canonical report additions

The additive `run.execution` object contains:

```json
{
  "jobs": {"requested": "auto", "effective": 4},
  "interruption_policy": "drain",
  "controllers": [{"name": "local", "parallel_capacity": 8}],
  "frontiers": [
    {"sequence": 1, "action_ids": ["git:verify:a", "git:verify:b"]}
  ]
}
```

An explicit numeric request is serialized as a number. Frontier action IDs are
always canonical even when starts and completions interleave. Existing event
timestamps and per-action durations remain the evidence of actual overlap.

## Consequences

`--jobs 1` remains the compatibility baseline. Drivers must explicitly declare
safe actions and resources before gaining concurrency. The first implementation
does not preempt running work, infer locks from planning claims, or provide fair
scheduling across separate Poly processes.
