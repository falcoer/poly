# External drivers

External drivers are ordinary Python distributions. They use the same public
`poly.driver`, `poly.driver.testkit`, and `poly.model` contracts as the built-in
Git and Maven drivers; importing internal application, planning, runtime, or
persistence modules is unsupported.

## Generate a repository

```shell
poly driver new example-tech --path ../poly-driver-example-tech
cd ../poly-driver-example-tech
uv sync --all-groups
```

During development against a local core checkout, add
`--poly-source /path/to/poly`. Without it, the generated dependency targets the
validated `roadmap/0.7-external-driver-kit` Git tag.

The generator creates:

- `poly-driver.toml`, a versioned declaration for explicit black-box checks;
- a `poly.drivers` package entry point for installed-driver discovery;
- one public `driver()` factory returning `DriverRegistration`;
- a deterministic marker-file example and fixture-backed conformance tests;
- strict Ruff, mypy, pytest/coverage, wheel, sdist, and GitHub Actions setup.

Both discovery conventions resolve the same factory. Poly validates the API
version, declared capabilities, provider names, and returned registration
before adding any provider to a registry. A broken third-party entry point is
reported as a rejection and cannot partially register itself.

## Develop the driver

Inspectors only observe the supplied workspace and return canonical nodes.
Planners answer only the requested verb and return a finite proposal. Every
action covers its requested nodes, declares its claim and required controller
capability, and contains either a complete command or a matching public action
handler. Missing prerequisites are constraints or diagnostics; a driver must
not invent another verb to satisfy them.

Use the generated fixture as a black-box example:

```shell
uv run poly-driver-test validate
uv run poly-driver-test inspect poly_driver_example_tech:driver \
  --workspace tests/fixtures/workspace
uv run poly-driver-test determinism poly_driver_example_tech:driver \
  --workspace tests/fixtures/workspace --verb sample-status
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv build
```

`validate` rejects incompatible manifests and registrations. `inspect` repeats
inspection and fingerprints the fixture to detect nondeterminism or side
effects. `determinism` applies the same checks to planning and also rejects
actions for a verb other than the requested one.

## Package and install

`uv build` produces a wheel and source distribution. Installing the wheel makes
the factory discoverable in the standard `poly.drivers` entry-point group. A
package-index release is deliberately outside the current policy; consume a
reviewed Git tag, wheel, or local path until an explicit release policy exists.
