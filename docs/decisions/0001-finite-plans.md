# ADR 0001: Negotiate finite plans

- Status: accepted
- Date: 2026-08-12

## Decision

Poly negotiates a finite action list from providers of the single requested
verb. It then validates claims and temporary constraints before execution. The
executor cannot append actions or resolve missing constraints by invoking other
verbs.

Structural applicability, conflict selection, and action ordering are distinct:

- applicability decides whether a candidate belongs in the plan;
- claims expose competing actions for the same operation and scope;
- `requires`/`produces` order only the actions already retained.

## Consequences

Plans terminate, dry-runs are faithful, and commands cannot produce surprising
side effects such as a `publish` silently building or testing a project. Drivers
must provide better diagnostics and explicitly calculate technology-specific
closure, such as Maven modules included through `-am`.
