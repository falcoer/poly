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

The current milestone is
[0.12.1 — Stable interactive CLI presentation](docs/releases/0.12.1.md).
It consolidates command-block rendering, captures handler and child-process
output per action, adds timestamped execution evidence, and exposes scalar
values plus typed file/URL deliverables without changing planning semantics.
Until the post-merge tag gate succeeds, the milestone remains
`implemented-awaiting-ci`, not `validated`.

The version 1 contract is implemented: manifests and locks are validated and
compiled into rebuildable state, declared identities are enriched by Git and
Maven inspection, and undeclared repositories remain explicit `observed-only`
nodes. Construction now uses the same negotiated, frozen plans and execution
runtime as technology verbs. Root bootstrap, recursive Git hydration, moving-ref
updates, and adoption of clean local `HEAD` commits are implemented through the
same reportable action model.

## Installation

Python 3.12 and Git are required. Maven and a Java runtime are required when
executing Maven verbs. For development snapshots, `uvx` and `uv tool install`
remain convenient:

```shell
uvx --from "git+https://github.com/falcoer/poly.git" poly --help
uv tool install "git+https://github.com/falcoer/poly.git"
```

For **0.12.1 functional acceptance**, reviewers install the retained CI wheel
instead of cloning Poly. Replace the run id and commit with the values from the
accepted CI run; artifact names deliberately include the exact build commit.

### POSIX retained-artifact journey

```bash
run_id="<accepted-run-id>"
commit="<accepted-commit>"

gh run download "$run_id" -R falcoer/poly \
  -n "poly-0.12.1-distributions-$commit" -D poly-dist
gh run download "$run_id" -R falcoer/poly \
  -n "poly-0.12.1-acceptance-fixture-$commit" -D poly-fixture

(cd poly-dist && sha256sum -c SHA256SUMS)
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install ./poly-dist/poly-0.12.1-py3-none-any.whl \
  ./poly-fixture/poly_driver_sample_tech-0.1.0-py3-none-any.whl

./poly-fixture/scripts/run-posix.sh \
  "$PWD/.venv/bin/python" "$PWD/.venv/bin/poly" \
  "$PWD/poly-fixture" "$PWD/poly-evidence"
```

### PowerShell retained-artifact journey

```powershell
$runId = "<accepted-run-id>"
$commit = "<accepted-commit>"

gh run download $runId -R falcoer/poly `
  -n "poly-0.12.1-distributions-$commit" -D poly-dist
gh run download $runId -R falcoer/poly `
  -n "poly-0.12.1-acceptance-fixture-$commit" -D poly-fixture

$sumLine = Get-Content .\poly-dist\SHA256SUMS |
  Where-Object { $_ -match "poly-0.12.1-py3-none-any.whl$" }
$expected = ($sumLine -split "\s+")[0].ToLowerInvariant()
$actual = (Get-FileHash .\poly-dist\poly-0.12.1-py3-none-any.whl -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "Poly wheel SHA-256 mismatch" }

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install `
  .\poly-dist\poly-0.12.1-py3-none-any.whl `
  .\poly-fixture\poly_driver_sample_tech-0.1.0-py3-none-any.whl

& .\poly-fixture\scripts\run-powershell.ps1 `
  -PythonExe .\.venv\Scripts\python.exe `
  -PolyExe .\.venv\Scripts\poly.exe `
  -FixtureDir .\poly-fixture `
  -OutputDir .\poly-evidence
```

Both routes execute the same checked-in acceptance logic and require no Poly
source checkout. The fixture is test input; `poly-dist` and `poly-evidence` are
generated/downloaded artifacts; within a real workspace only committed
`poly.yaml`, `poly.lock.yaml`, and the root `.gitignore` composition contract
are persistent, while `.poly/` is disposable generated state.

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
poly inspect --format json --output reports/inspection.json
poly drivers
poly nature list
poly controllers
poly init --name example --plan
poly init --name example
poly add service-api --path services/api \
  --repo https://git.example.com/team/service-api.git --ref main
poly add service-api-reactor --parent service-api --path . --nature maven/reactor
poly nature add . maven/reactor java/project
poly nature remove . java/project
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
`poly inspect --output <file>` writes the selected format atomically and keeps a
compact terminal result whose `OUTPUT` section links to the generated report.
`run` stores process output and state transitions in its report. It executes
only the frozen plan printed in the same document.

Interactive text output is grouped into one visual block per command: an
action-oriented heading, an indented plan, one detailed status line per action,
and a framed success or failure summary. For executed plans, the heading and
plan are flushed before work begins; `RUNNING`, `OK`, `KO`, and `WARN` lines
then appear as each action changes state, so long operations such as
materialization also update the native iTerm2 or Windows Terminal progress
indicator. The indicator is cleared when the plan completes or is interrupted.
`poly hydrate` never waits for the final report before showing progress. Use
`-q` for only the unchanged final result,
`-v` to also show the exact invoked command and process output, and `-vv` for
the complete canonical report. Colors are automatic on terminals and can be
controlled with `--color auto|always|never`; `NO_COLOR` is honored. Structured
JSON, YAML, and XML output is never decorated.

`poly init` creates `poly.yaml`, `poly.lock.yaml`, compiled state, and the
delimited root `.gitignore` block. Re-running it reconciles those generated
artifacts without changing authored composition. `poly add` and `poly remove`
edit the YAML round-trip document while preserving comments and user-owned
ignore rules. A Git-backed `add --repo` resolves the requested selector, stores
the exact commit in `poly.lock.yaml`, and atomically updates the composition
without creating or changing the child worktree. `poly hydrate` is the explicit
materialization step. All construction commands remain ordinary driver
proposals rather than a private CLI execution path.

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

0.12 excludes the Web UI, parallel execution, child commit/push/merge, public
package-index publication, and hostile-driver sandboxing. A milestone tag is
created by CI only after every required check succeeds on the exact milestone
commit.

## Core rule

An absent constraint is a diagnostic, not permission to invent another verb.
For example, `publish` providers may propose publish actions only; Poly never
adds an implicit `build`, `test`, or `package` operation to make them possible.
