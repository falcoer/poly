# Driver SDK

Every built-in and external driver registers through `poly.driver`. There is no
privileged API for drivers shipped in the Poly repository.

## Manifest compatibility

The current driver API is `1.0`. A driver manifest declares its identity,
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
    api_version="1.0",
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
