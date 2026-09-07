# Plugin Extension API and Rust migration boundary

## Objective

This document records the architectural boundary agreed before Poly 0.13 so that later sessions can continue implementation without relying on conversational context.

The target is a language-independent extension model in which drivers, facades, and blueprints are contributions packaged by plugins, while the Poly core remains the only orchestration authority.

## Stable architectural boundary

The public extension boundary must expose serializable domain concepts only. Extensions may receive controlled context and return contributions, actions, outputs, diagnostics, and results. They must not depend on scheduler internals, renderer state, Python object identity, mutable core services, or implementation-specific runtime objects.

The desired separation is:

```text
Plugin contributions
        |
        v
Poly Extension API
        |
        v
validated contributions / actions
        |
        v
Poly planner and frozen DAG
        |
        v
scheduler / executor / event dispatcher
        |
        v
reports / CLI / structured output
```

## Plugin model

A plugin is the extension container:

```text
Plugin
├── metadata
│   ├── id
│   ├── version
│   ├── Poly API compatibility
│   └── optional dependencies
├── drivers
├── facades
├── blueprints
└── optional resources
```

The plugin is the unit of discovery, packaging, compatibility, and future installation. Drivers are no longer the fundamental packaging unit; they are one contribution type.

## Contribution responsibilities

### Driver

A driver owns technology/domain knowledge. It may inspect, propose executable actions, and execute actions assigned to it. It never chooses scheduler policy or imperatively invokes another driver.

### Facade

A facade translates high-level user vocabulary into normalized intent or contributions. It does not execute nested plans or gain privileged core access.

### Blueprint

A blueprint describes desired composition or structure. It is primarily declarative. Any future hook must use the same public contribution contract and must not access core internals directly.

### Poly core

Poly alone owns:

- workspace invariants and validated mutation;
- plan construction and validation;
- DAG and dependency semantics;
- action admission and frontier selection;
- scheduling and bounded parallelism;
- retry, timeout, cancellation, and interruption policy;
- state and persistence;
- event ordering;
- reporting and terminal rendering.

The governing rule is: **extensions know their domain; Poly owns orchestration**.

## Serialization invariant

Everything crossing the extension boundary must be representable without runtime callbacks or object references.

Actions and results must therefore remain suitable for canonical JSON/YAML/XML or another explicit wire representation. A frozen plan must not contain Python functions, executor objects, thread pools, mutable workspace objects, or opaque implementation-specific references.

This invariant is both a persistence requirement and the principal enabler for a later process boundary and Rust core.

## Workspace access

Extensions should receive a controlled `WorkspaceView`-style API or equivalent serializable context. They must not receive unrestricted mutable access to the core workspace model.

Changes requested by a facade, blueprint, or driver are returned as contributions and applied only after core validation. This keeps workspace invariants under Poly ownership.

## No nested orchestration

Extensions must not call one another imperatively and must not recursively invoke the Poly scheduler.

Dependencies are expressed declaratively as requirements, produced constraints, action dependencies, or validated contributions. Poly resolves these relationships centrally.

This is mandatory for 0.13 because nested schedulers would make deadlock handling, cancellation, event ordering, failure isolation, and deterministic reporting substantially harder.

## Built-in versus external contributions

Built-in and external contributions should have equivalent functional rights under the public Extension API. An in-process built-in implementation may be faster, but it must not rely on a semantically richer private API.

This avoids creating a two-tier ecosystem where important capabilities can only be implemented in the Poly core language.

## Logical API versus transport

The logical Extension API is independent from its transport.

The first implementation may remain in-process Python. A later transport can be introduced without changing semantics, for example:

- stdio with a versioned JSON protocol;
- JSON-RPC;
- gRPC;
- sockets;
- WebAssembly;
- another explicit protocol.

The transport must be replaceable and must not leak into the planner or scheduler model.

## 0.12.6 milestone

0.12.6 establishes the plugin and contribution architecture before parallel scheduling:

- `Plugin` descriptor and compatibility metadata;
- `PluginRegistry`;
- `ContributionRegistry` for drivers, facades, and blueprints;
- stable contribution identities;
- current drivers represented as plugin-owned contributions;
- current facades resolved as contributions;
- blueprint registration reserved as a first-class type;
- Extension API invariants formalized and conformance-tested;
- no marketplace, sandbox, remote transport, or blueprint engine yet.

## 0.13 milestone

0.13 remains the bounded parallel execution milestone. It builds on 0.12.6 and owns:

- frozen DAG/frontier execution;
- bounded worker scheduling;
- runtime execution-resource isolation;
- failure isolation;
- cancellation and interruption semantics;
- synchronized event publication;
- concurrent live/flow rendering through the sole terminal owner;
- deterministic final reports.

The scheduler must refer only to stable contribution/action identities and public contracts. It must not know whether the executing contribution is Python, Rust, Java, TypeScript, or built in.

The Python implementation realizes this boundary with serializable action-level
`execution_resources` and `concurrency_safe` declarations. The executor receives
only a frozen action plus an execution adapter, creates per-action contexts, and
never branches on plugin packaging or Python object identity. Extensions still
cannot own pools, frontiers, event sequences, cancellation, or terminal output.

## Rust migration gate

The end of validated 0.13 is the first intended point at which a serious Rust port should be evaluated.

The Python 0.13 implementation is to be treated as an **executable specification**, not as source code to translate line by line.

A Rust implementation must preserve at minimum:

- `poly.yaml` semantics;
- `poly.lock.yaml` semantics;
- plan and action semantics;
- extension identities and compatibility contracts;
- result/output/diagnostic models;
- failure and cancellation semantics;
- public CLI behavior where deliberately stable;
- persisted canonical report behavior;
- conformance fixtures and cross-platform acceptance tests.

The migration should compare Python and Rust implementations against the same fixtures and externally observable outcomes.

The intervening [0.13.1 executable-specification milestone](../releases/0.13.1.md)
turns this gate into versioned fixtures, a black-box conformance corpus, and a
differential runner. Rust implementation starts only after that parity baseline
is validated.

## Future multi-language extensions

Once the logical boundary is validated, a later milestone may introduce an out-of-process transport allowing contributions implemented in Rust, Python, Java, TypeScript, Go, or other languages.

That future capability must not require redesign of plan semantics or 0.13 scheduling. If adding a transport requires scheduler-specific exceptions or exposing core internals, the 0.12.6 boundary should be considered incomplete.

## Deferred capabilities

Do not implicitly expand the executable-specification work into:

- marketplace design;
- remote plugin repositories;
- automatic dependency download;
- plugin trust/sandbox policy;
- distributed scheduler;
- full blueprint language;
- driver-managed concurrency;
- runtime plan expansion.
