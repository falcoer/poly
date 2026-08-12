# Workspace construction

`poly init` and `poly add` are constructor operations, not special filesystem
shortcuts. Each command first produces a finite plan whose actions declare
`workspace.construct`, then sends that plan through the common executor and
control-plane.

```shell
poly init --workspace ./example --name example
poly add service-api \
  --workspace ./example \
  --path services/api \
  --nature maven/module
```

Initialization targets an existing directory and creates a versioned
`.poly/workspace.json` definition. Adding a node creates its safe
workspace-relative directory and records its identifier, path, and declared
natures. Duplicate identifiers, duplicate paths, root paths, and parent-path
escapes are rejected while constructing the plan, before execution.

Both operations produce ordinary canonical run reports and can be recovered
later with `poly report <plan-id>`.
