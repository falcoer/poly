# Workspace construction

`poly init`, `poly add`, and `poly remove` are constructor operations, not
special filesystem shortcuts. Each command first produces a finite plan whose actions declare
`workspace.construct`, then sends that plan through the common executor and
control-plane.

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
