# Git reference driver

`poly.driver.git` proves that a built-in driver can use only the public SDK.

During inspection it discovers worktrees from `.git` directories and `.git`
files, so linked worktrees and nested repositories remain distinct nodes. A
nested repository receives a `git/nested-under` relation to its nearest Git
ancestor. Each node exposes:

- nature `git/repository`;
- workspace-relative repository root;
- symbolic branch or detached state;
- current HEAD when one exists;
- clean/dirty state;
- bare-repository state.
- origin URL when available;
- relation of local `HEAD` to the committed Poly lock (`current`,
  `ahead-of-lock`, `behind-lock`, `diverged`, or unavailable).

Inspection executes read-only Git commands with a bounded timeout. Invalid
repository markers become diagnostics instead of aborting other discoveries.

For the `status` verb, the driver proposes one action per selected Git node:

```text
git -C <workspace-relative-root> status --short --branch
```

Non-Git nodes are retained as rejected candidates with the missing
`nature:git/repository` explanation.

## Materialization and lock lifecycle

Git-backed construction and restoration are frozen action graphs. Resolution,
clone or adoption, fetch-if-needed, checkout, and exact `HEAD` verification are
separate visible actions. Parent repository verification constrains nested
repository materialization, so a nested checkout is never created before its
owning repository.

```shell
poly add api --path services/api --repo https://git.example/api.git --ref main
poly hydrate
poly update --select api
poly lock --from-workspace --select api
```

`add` resolves the current requested reference into `poly.lock.yaml` and then
materializes it. `hydrate` always follows the immutable lock and is a no-op when
the checkout already matches. `update` resolves the moving reference, moves a
clean worktree safely, verifies its new `HEAD`, and only then updates the lock.
`lock --from-workspace` records clean local `HEAD` commits, which is the explicit
way to adopt pulls performed by EGit or another Git client.

Worktree movement is refused for dirty repositories. Existing repositories are
adopted only when their origin matches the declaration; non-empty non-Git
targets, partial clones, unavailable locked commits, and non-fast-forward branch
movement fail explicitly. No Git submodule is created.

`poly inspect --remote` uses `git ls-remote` and does not mutate local refs. It
reports whether a requested remote ref still equals the lock.
