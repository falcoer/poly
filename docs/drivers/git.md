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

Inspection executes read-only Git commands with a bounded timeout. Invalid
repository markers become diagnostics instead of aborting other discoveries.

For the `status` verb, the driver proposes one action per selected Git node:

```text
git -C <workspace-relative-root> status --short --branch
```

Non-Git nodes are retained as rejected candidates with the missing
`nature:git/repository` explanation. Mutating Git verbs are intentionally
deferred beyond this reference milestone.
