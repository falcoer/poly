# Workspace construction

`poly init`, `poly add`, and `poly remove` are proposals from the system driver
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
optional natures without materializing a Git source. Repository paths enter the
managed ignore block; removal deletes only the corresponding declaration and
managed rule, never the repository directory. YAML comments and ordering, plus
all user-owned ignore rules, are preserved.

Unknown fields, duplicate identifiers, graph cycles, lexical or symlink path
escapes, case-insensitive collisions, stale locks, embedded credentials, and
malformed managed markers are rejected while constructing the plan, before
execution. The provisional `.poly/workspace.json` format is explicitly rejected
with a migration diagnostic.

All operations produce ordinary canonical run reports and can be recovered
later with `poly report <plan-id>`.
