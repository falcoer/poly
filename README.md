# Poly

Poly is a deterministic polyrepo engine. It separates five roles:

- the **constructor** changes the composition of a workspace;
- the **inspector** observes nodes, natures, metadata, and relations;
- the **orchestrator** negotiates one requested verb into a finite plan;
- the **executor** runs that frozen plan without inventing more work;
- the **reporter** renders the same canonical state for humans and tools.

Technology knowledge lives in versioned drivers. The built-in Git and Maven
drivers use the same public SDK and conformance suite as external drivers.

The Git reference driver discovers root and nested repositories, observes
branch/HEAD/cleanliness without changing them, and negotiates explicit read-only
`status` actions. The Maven reference driver distinguishes inheritance from
aggregation, groups selected modules at their highest local reactor, and makes
cross-reactor materialization and ordering explicit in the plan.

## Status

Poly is being implemented from scratch. The executable milestones, acceptance
criteria, and validation tags are tracked in [ROADMAP.md](ROADMAP.md).

The converged workspace model is specified in
[Workspace files contract](docs/reference/workspace-files.md): the root node
owns committed `poly.yaml` and `poly.lock.yaml`, while independently versioned
child repositories and generated `.poly/` state are excluded through a
Poly-managed root `.gitignore` block.

For a command-oriented tour, see the [Poly cookbook](docs/cookbook/README.md).

The version 1 contract is implemented: manifests and locks are validated and
compiled into rebuildable state, declared identities are enriched by Git and
Maven inspection, and undeclared repositories remain explicit `observed-only`
nodes. Construction now uses the same negotiated, frozen plans and execution
runtime as technology verbs. Root bootstrap, recursive Git hydration, moving-ref
updates, and adoption of clean local `HEAD` commits are implemented through the
same reportable action model.

## Installation

Python 3.12, Git, and [uv](https://docs.astral.sh/uv/) are required. To run Poly
once without keeping the tool installed:

```shell
uvx --from "git+https://github.com/falcoer/poly.git" poly --help
```

For daily use, install the `poly` command in an isolated environment managed by
uv:

```shell
uv tool install "git+https://github.com/falcoer/poly.git"
poly --help
```

Commands in this README and in the cookbook then assume that `poly` is directly
available on `PATH`.

## Development

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required.

```shell
uv sync --locked --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv build
```

Generate a standalone external driver repository with the same public API and
quality gates as built-in drivers:

```shell
poly driver new example-tech --path ../poly-driver-example-tech
cd ../poly-driver-example-tech
uv sync --all-groups
uv run poly-driver-test validate
```

The generated package includes a versioned manifest, a `poly.drivers` entry
point, deterministic fixture tests, CI, wheel/sdist packaging, and no imports
from privileged core modules. See [External drivers](docs/drivers/external.md).

## Local CLI

Driver verbs execute directly; add `--plan` for a side-effect-free frozen plan.
The `plan` and `run` expert façades use the same application service and produce
the same plan identifier. `actions` remains a fresh catalog of what the current
workspace can do.

```shell
poly inspect
poly drivers
poly controllers
poly init --name example --plan
poly init --name example
poly add service-api --path services/api \
  --repo https://git.example.com/team/service-api.git --ref main
poly add service-api-reactor --parent service-api --path . --nature maven/reactor
poly remove service-api-reactor
poly hydrate
poly inspect --remote
poly lock --from-workspace --select service-api
poly update --select service-api
poly status
poly verify --select service-api-reactor
poly actions
poly actions verify --select maven:platform/service-a
poly plan verify --select maven:platform/service-a --format yaml
poly run status --select root --format json
poly report <run-id> --format xml
```

Every command accepts `--workspace`. Reports support `text`, `json`, `yaml`,
and `xml`; all formats are rendered from the same `poly.report/v1` document.
`run` stores process output and state transitions in its report. It executes
only the frozen plan printed in the same document.

`poly init` creates `poly.yaml`, `poly.lock.yaml`, compiled state, and the
delimited root `.gitignore` block. Re-running it reconciles those generated
artifacts without changing authored composition. `poly add` and `poly remove`
edit the YAML round-trip document while preserving comments and user-owned
ignore rules. A Git-backed `add --repo` resolves, locks, and materializes its
source as one composite job; a structural add without `--repo` only declares the
node.
All three are ordinary constructor-driver proposals rather than a private CLI
execution path.

Clone a committed control repository and restore every locked descendant in one
reported job:

```shell
poly init https://git.example.com/team/workspace.git ./workspace --ref main
```

Normal restoration follows `poly.lock.yaml`. A branch advanced by Eclipse/EGit
is not reset implicitly: inspection reports `ahead-of-lock`, `behind-lock`, or
`diverged`. `poly lock --from-workspace` explicitly adopts clean local `HEAD`
commits; `poly update` resolves requested remote references, safely materializes
and verifies them, then rewrites the lock. `poly inspect --remote` compares the
lock with the remote without fetching or modifying local repositories.

The project advances directly on `main`. A milestone tag is created by CI only
after every required check succeeds on the exact milestone commit.

## Core rule

An absent constraint is a diagnostic, not permission to invent another verb.
For example, `publish` providers may propose publish actions only; Poly never
adds an implicit `build`, `test`, or `package` operation to make them possible.
