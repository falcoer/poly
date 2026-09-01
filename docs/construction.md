# Workspace construction

`poly init`, `poly add`, `poly remove`, and contextual nature changes are proposals from the system driver
`poly.constructor`, not special filesystem shortcuts. They use the public
planning, execution, control-plane, logging, and reporting contracts.

Typed CLI options translate to canonical planning parameters. These two forms
therefore produce the same frozen plan identifier and action list:

```shell
poly add api --path services/api --plan
poly plan add \
  --parameter poly.node.id=api \
  --parameter poly.node.path=services/api \
  --parameter poly.node.kind=module \
  --parameter poly.node.natures=
```

Without `--plan`, direct verbs execute the plan and persist the same run report
as the expert `poly run <verb>` façade.

```shell
poly init --workspace ./example --name example
poly add service-api \
  --workspace ./example \
  --kind repository \
  --path services/api
poly add service-api-reactor \
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
optional natures. With `--repo`, the same composite job resolves the requested
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
