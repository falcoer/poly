# Workspace construction

`poly init`, `poly add`, `poly remove`, and contextual nature changes are proposals from the system driver
`poly.constructor`, not special filesystem shortcuts. They use the public
planning, execution, control-plane, logging, and reporting contracts.

Each loaded driver may contribute an `add` facade that translates typed CLI
arguments to canonical planning parameters. The engine does not enumerate
facade names or technologies:

```shell
poly add module api --path services/api --plan
poly add repository api-source --path sources/api --repo https://git.example/api.git --plan
```

Without `--plan` or `--prepare`, direct verbs execute immediately. `--prepare`
appends to one disposable current plan; `poly plan` displays it, `poly exec`
executes it without replanning, and `poly plan clean` discards it.

```shell
poly init --workspace ./example --name example
poly add repository service-api \
  --workspace ./example \
  --path services/api
poly add module service-api-reactor \
  --workspace ./example \
  --parent service-api \
  --path . \
  --nature maven/reactor
```

Initialization targets an existing directory and creates the committed
`poly.yaml` intent and `poly.lock.yaml` resolution files. It compiles disposable
`.poly/state/workspace.json`, and owns only the delimited Poly block in the
root `.gitignore`. Re-running `init` validates and reconciles these generated
artifacts.

Adding a node records its stable identifier, kind, parent-relative path, and
optional natures. With `poly add repository --repo`, the same composite job resolves the requested
Git ref, writes its immutable lock entry, and updates the ignore block without
cloning, fetching, adopting, or checking out the child. `poly hydrate` performs
that materialization explicitly. Without `--repo`, `add` remains a structural declaration.
Repository paths enter the managed ignore block; removal deletes only the
corresponding declaration and managed rule, never the repository directory.
YAML comments and ordering, plus all user-owned ignore rules, are preserved.

`poly nature list` returns the alphabetically ordered nature contributions of
the loaded drivers. From any declared node directory, `poly nature add` and
`poly nature remove` find the nearest workspace and closest current node. They
accept an explicit `.` and multiple values in one atomic change:

```shell
poly nature add . maven/reactor java/project
poly nature remove . java/project
```

Unknown fields, duplicate identifiers, graph cycles, lexical or symlink path
escapes, case-insensitive collisions, stale locks, embedded credentials, and
malformed managed markers are rejected while constructing the plan, before
execution. The provisional `.poly/workspace.json` format is explicitly rejected
with a migration diagnostic.

All operations produce ordinary canonical run reports and can be recovered
later with `poly report <plan-id>`.
