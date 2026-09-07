# Poly Extension API and Driver SDK

Every built-in and external driver registers through `poly.driver`. There is no
privileged API for drivers shipped in the Poly repository.

Since Poly 0.12.6, plugins are the extension container and drivers are one
contribution type. Existing `DriverRegistration` factories remain compatible:
Poly wraps each legacy driver in an implicit plugin and indexes its driver and
facade contributions through `ContributionRegistry`.

An explicit plugin returns `PluginRegistration` from the `poly.plugins` entry
point group. Its serializable `Plugin` descriptor declares stable contribution
identities, Extension API compatibility, optional dependencies, and resources.
Drivers use `driver:<name>`, facades use `facade:<verb>:<name>`, and blueprints
use `blueprint:<name>`. Blueprint lookup is reserved in 0.12.6; execution is not
yet part of the public contract.

## Manifest compatibility

The current driver API is `1.1`; the containing Poly Extension API is `1.0`. A
driver manifest declares its identity,
implementation version, API version, exact capability set, and the stable
natures it contributes. Poly accepts the
same major version up to its supported minor version. A future incompatible API
will therefore fail during registration, before driver code can participate in
inspection, planning, or execution.

```python
from poly.driver import DriverCapability, DriverManifest

manifest = DriverManifest(
    name="example.driver",
    version="0.1.0",
    api_version="1.1",
    capabilities=frozenset((DriverCapability.INSPECT, DriverCapability.PLAN)),
    natures=("example/project",),
)
```

The registration must provide exactly the declared capability kinds, and every
provider must use the manifest name. Duplicate driver names are rejected.

## Provider boundaries

- `InspectionProvider` observes a workspace and returns canonical nodes and
  diagnostics.
- `PlanningProvider` declares supported verbs and returns a proposal for one
  immutable planning request.
- `ActionHandler` performs a fully specified non-command action and returns a
  structured `DriverExecutionResult`.

Planning and inspection are read-only. The executor is the only role authorized
to invoke an action handler.

## Parallel execution declarations

Poly 0.13 keeps scheduling in the core. An `ActionSpec` may declare
`execution_resources`, a serializable set of exclusive runtime resource names,
and must set `concurrency_safe=True` to opt into concurrent admission. These
resources are runtime locks only; they are independent from planning
`ActionClaim` ownership and do not resolve provider conflicts.

The default is deliberately conservative. Actions that do not opt in, including
existing command-less external handlers, execute alone. Structural actions also
remain serialized unless their driver has explicitly audited and opted in the
action. Built-in Git materialization uses `repository:<node-id>` and Maven uses
`reactor:<id>`, so independent repositories/reactors can overlap while operations
on one resource cannot. Drivers must not create their own scheduler or thread
pool.

Every handler receives `ExecutionContext.action_directory`, an isolated location
below the run directory for action-specific artifacts. `${POLY_ACTION_DIRECTORY}`
provides the equivalent placeholder to explicit commands. Poly captures and
persists stdout, stderr, and structured details per action.

## Conformance testkit

`poly.driver.testkit` contains black-box assertions intended to be imported by
external driver test suites. They verify manifest round-tripping and protocol
compatibility, repeat inspection and planning to detect nondeterminism, and
fingerprint the fixture workspace before and after each call to detect effects.

```python
from poly.driver.testkit import assert_planning_deterministic

proposal = assert_planning_deterministic(provider, request, fixture_workspace)
```

The testkit is evidence, not documentation-only guidance. The external driver
generator uses it in a technology-neutral fixture and in clean-room CI. See
[External drivers](external.md) for the complete repository workflow.
