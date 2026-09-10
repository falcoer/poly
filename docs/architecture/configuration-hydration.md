# Configuration nodes and hydration

Implementation correction for 0.13.2, 2026-09-10. This supersedes the prototype's
standalone configuration command and navigation-only lifecycle.

## Declaration

A projection is represented by a normal configuration node in the root-owned
`poly.yaml`. Its driver contributes an `add` facade, a versioned JSON Schema and
ordinary `hydrate` planning/execution providers. There is no projector registry,
application switch in the engine, or separate configuration lifecycle.

```yaml
- id: ide
  kind: configuration
  parent: root
  natures: [fixture/eclipse-configuration]
  configuration:
    schema: fixture.eclipse/workspace/v1
    values:
      name: Demo
```

This example is the external contract fixture, not the production Eclipse schema.
Configuration nodes have no source path. Their target directory is determined by
the owning driver's configuration and local bindings. Other kinds still require
a workspace-relative path. A physical node cannot have a pathless parent.

The constructor persists the declaration and updates the manifest digest in the
lock. `ConfigurationAddFacade` accepts an identifier, optional `--parent`, and
optional `--file` with YAML values. A blueprint can resolve reusable values before
that declaration. The resulting values are saved, rather than depending on a
blueprint being re-resolved during onboarding. No live blueprint inheritance or
configuration editing command is introduced in this correction.

`ConfigurationSchema(identity, schema)` validates JSON Schema Draft 2020-12.
References must be local to that schema document. Configuration envelopes contain
exactly `schema` and `values`; schemas define allowed values and unknown-field
policy. Registration rejects duplicate schema identities. `add` and `hydrate`
planning reject unknown schemas or invalid values with a field-level diagnostic.
There is no automatic schema migration or downloaded schema resolution.

## Finite hydration plan

Hydration starts from the declared inventory, including repositories that do not
exist locally yet. It does not rely on a pre-checkout scan to elect source
inspectors. A driver opts in with `source_inspectors=(provider,)`; its context
contains the declared `source`, while `workspace` remains the composition root.
One source inspector per driver can return multiple projects and natures.

Every source has an identity-specific `source_available(id)` fact. Git produces
it only after checking the locked HEAD. A local source without a checkout provider
has an ordinary directory-check action. Each elected inspection action requires
that source's availability and produces its own completion fact. Inspections on
different available sources may run concurrently.

`workspace.coherence` is explicitly present in the plan. It waits for every
expected availability and inspection fact, checks that the declaration has not
changed, reconciles the observations, validates configuration contracts, and
writes a run-local inventory. Only success produces `WORKSPACE_COHERENT`.
Projection actions require that fact and read `hydration_inventory(context)` from
the public SDK. Discovering Maven modules enriches this inventory; it never adds
an action to the running plan. Further technology-specific coherence rules can
be implemented as explicit driver actions using these ordinary facts.

When a configuration node is selected, coherence requires the full declared
source scope. Selecting only the configuration does not implicitly add checkout
actions: the plan is blocked if a required source has no availability producer.
Use the complete `poly hydrate` plan for onboarding. A selected configuration with
no proposed hydration action is a planning error, even if its schema is known.
Failed actions do not produce their facts; independent work can continue, but the
run cannot succeed while any action remains failed or blocked.

Maven source inspection reads the root POM and follows explicit module references,
rejecting references escaping the source boundary. It does not recursively walk
source code. The older workspace-wide `inspect` discovery/cache remains separate;
this correction does not claim that all historical scanning has been rewritten.

## Nature provenance

Effective natures are the union of manually declared, structural and current
observed natures. `nature_origins` identifies `declared`, `structural`, and
`observed:<driver>` for each nature. Reinspection can remove an observation but
cannot remove a manual declaration. The distinction survives JSON reporting and
inspection-cache round trips. Observations remain disposable local state.

## SDK compatibility

Driver API and Extension API are **2.0**. `Node.path` can now be `None`; providers
must check applicability before filesystem work and use `require_path()` when a
physical path is required. This is an intentional major revision: older drivers
are rejected at loading rather than silently receiving an incompatible model.
The new configuration and source-inspection contributions are exposed through
`poly.driver`. Existing generic action, constraint, executor and controller
semantics are retained. No Eclipse type enters the planner or runtime.

## Proof and remaining delivery

`tests/test_hydration_configuration.py` checks reconstruction into two independent
local roots from the same authored composition and locked Git commit, inspections
after checkout, module discovery within a fixed plan, nature provenance, missing
sources, schema errors and stale declarations. The external fixture consumes the
consolidated inventory and materializes a deterministic request directory; it
also refuses to overwrite differing fixture output.

The production Eclipse importer is not implemented by this correction. The
fixture does not open Eclipse, create a real Eclipse workspace, or apply working
sets. No production `eclipse-configuration` facade is bundled yet. Real headless
import, target product/plugin validation, shared settings and local bindings,
working-set application, and Windows/POSIX acceptance remain the next delivery.
See [the Eclipse import requirements](eclipse-workspace-import.md).
