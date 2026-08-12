# Poly external-driver contract

## Public surface

- `poly.driver`: API version, manifest, registration, contexts, provider
  protocols, registry, and discovery constants.
- `poly.model`: canonical node, inventory, request, proposal, action, claim,
  constraint, and diagnostic value objects.
- `poly.driver.testkit`: manifest, inspection, and planning conformance
  assertions.

Do not import `poly.application`, `poly.planning`, `poly.runtime`,
`poly.persistence`, or built-in driver implementation modules.

## Packaging

Keep `poly-driver.toml` spec version `1` and a matching entry point:

```toml
[driver]
spec-version = "1"
name = "poly.driver.example"
entrypoint = "poly_driver_example:driver"

[project.entry-points."poly.drivers"]
example = "poly_driver_example:driver"
```

The factory must return a validated `DriverRegistration`. Its manifest name
must match the explicit declaration and every provider name. Its exact
capability set must match the registered provider kinds. The current driver API
is `1.0`.

## Behavioral invariants

- Inspection reads only its `InspectionContext` and returns stable, sorted
  canonical observations.
- Planning reads one immutable `PlanningRequest`, supports its verb explicitly,
  and returns the same proposal for identical input.
- Each action uses the requested verb, covers its `requested_node_ids`, declares
  an exclusive operation/scope claim, and identifies its controller capability.
- A planner reports missing constraints; it does not synthesize build, test,
  package, publish, or other prerequisite verbs.
- Execution is the only phase allowed to mutate state. A handler executes only
  the frozen action it receives.

## Required gates

```shell
uv run poly-driver-test validate
uv run poly-driver-test inspect <module>:driver --workspace <fixture>
uv run poly-driver-test determinism <module>:driver --workspace <fixture> --verb <verb>
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv build
```

Test at least one valid fixture, absence/non-applicability, malformed or
incompatible registration, selection coverage, deterministic ordering, and the
declared packaging entry point.
