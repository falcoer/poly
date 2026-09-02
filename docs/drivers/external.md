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
`--poly-source /path/to/poly`. This writes a development-only `uv` source while
the built distribution retains the portable requirement `poly>=0.12.0,<0.13`.

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

At production startup Poly enumerates every installed `poly.drivers` entry point
in a canonical order and resolves all candidates before accepting any of them.
An identity duplicated by two installed distributions is rejected on both
sides. Installed drivers that contribute the same verb are likewise all
rejected. A candidate conflicting with a core identity, requiring an
incompatible protocol, or failing during import is isolated without disabling
the remaining drivers. Entry-point enumeration order therefore never chooses a
winner.

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

## Inventory and load states

Run `poly drivers` against any existing directory or workspace:

```shell
poly drivers --workspace . --format text -vv
poly drivers --workspace . --format json
```

Every entry includes `name`, `version`, `origin`, `api_version`, `capabilities`,
`verbs`, `status`, `entry_point`, and `diagnostic`. Core origins are `system` or
`builtin`; installed origins identify the contributing distribution. A status
of `loaded` means its providers are active. A status of `rejected` means they are
completely inactive and `diagnostic` explains the import, protocol, identity, or
verb conflict. The same driver inventory is embedded in inspection, action,
plan, and run reports in text, JSON, YAML, and XML.

## End-to-end installed-wheel example

The following development journey uses only public commands and wheel
installation. The release acceptance journey that downloads the retained CI
wheel without checking out Poly source is documented in
[0.12.0 release notes](../releases/0.12.0.md).

```shell
uv build
poly driver new sample-tech --path ../poly-driver-sample-tech --poly-source "$PWD"
(cd ../poly-driver-sample-tech && uv build)

uv venv ../poly-clean-room
uv pip install --python ../poly-clean-room/bin/python \
  dist/poly-0.12.0-py3-none-any.whl \
  ../poly-driver-sample-tech/dist/poly_driver_sample_tech-0.1.0-py3-none-any.whl

POLY=../poly-clean-room/bin/poly
mkdir -p ../sample-workspace
"$POLY" init --workspace ../sample-workspace --name Sample --format json
printf 'sample\n' > ../sample-workspace/sample.project
"$POLY" drivers --workspace ../sample-workspace --format json
"$POLY" sample-status --workspace ../sample-workspace --select root --format json
"$POLY" report RUN_ID --workspace ../sample-workspace --format json
```

Replace `RUN_ID` with the `plan.id` printed by the direct-verb run. Its ordinary
run report contains the external action, state-transition events, stdout,
stderr, summary, and details. The sample inspector's `sample/project` nature is
merged into the existing canonical `root` node rather than creating a private
parallel model.

## Security boundary

Poly 0.12 validates declarations and isolates load failures, but it does not
sandbox hostile code. Importing an installed driver executes Python in Poly's
process, and its action handler has the process permissions of the invoking
user. Install only reviewed and trusted driver wheels. Operating-system
sandboxing, privilege separation, and hostile-plugin containment are explicitly
outside the 0.12 scope.
