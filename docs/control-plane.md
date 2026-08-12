# Control-plane

Every action carries one required controller capability. Built-in command
actions currently require `process.execute`; constructor actions require
`workspace.construct`. The control-plane selects a controller only when its
descriptor advertises the exact capability.

```shell
poly controllers
poly run status --select git:. --controller local
```

A controller descriptor has a stable name, platform, capability set, and an
optional endpoint. Local and remote controllers implement the same action-runner
contract. Remote calls use versioned `poly.controller.request/v1` and
`poly.controller.response/v1` documents with a correlated request identifier,
required capability, action, workspace, run directory, attempt status, logs,
exit code, and structured details.

The initial CLI registers one local controller. The remote transport is a
protocol extension point: HTTP, MCP, or another transport can implement it
without changing planning or execution semantics.
