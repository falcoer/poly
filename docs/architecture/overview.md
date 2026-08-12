# Architecture overview

Poly is a deterministic engine whose software agents are roles, not autonomous
LLMs. Technology-specific decisions are delegated to drivers, while authority
over effects remains centralized.

```text
constructor ─┐
             ├─> finite plan ─> executor ─> events/results
orchestrator ┘         ^                         |
      ^                |                         v
      |             drivers                  reporter
  inventory <──────── inspector
```

## Responsibility boundaries

The constructor proposes structural changes such as `init` and `add`. The
inspector observes nodes, stable natures, metadata, and relations. The
orchestrator asks providers of exactly one verb to negotiate a finite plan. The
executor orders that plan by temporary constraints and never renegotiates it.
The reporter renders canonical inventories, proposals, plans, events, and
results without recalculating business rules.

Drivers supply technology knowledge to one or more roles. A Maven driver may
group ten selected nodes into one reactor action; Poly does not reproduce
Maven's internal ordering. Between distinct reactors, the same driver emits
ordinary action constraints that the generic executor understands.

## State

Only observed structure is eligible for durable inventory. Action completion
constraints exist for a single run. Volatile facts such as a generated JAR are
revalidated when a verb needs them and are never trusted solely because they
appeared in an older inventory.

## Planning invariant

Negotiation is closed over the requested verb:

1. resolve selection and current inventory;
2. ask providers registered for that verb;
3. aggregate and validate their proposals;
4. expose accepted and rejected candidates;
5. freeze the plan;
6. order and execute only its actions.

Missing prerequisites block an action. They do not trigger recursive discovery
of another verb capable of producing them.

## Initial runtime

The local runtime is deliberately sequential. It continues independent work
after a failure and marks dependants blocked when their declared constraints
were not produced. Commands and driver handlers share one action-attempt model,
so the reporter does not need technology-specific logic. The initial CLI
exposes `inspect`, `actions`, `plan`, and `run` without collapsing their distinct
meanings.
