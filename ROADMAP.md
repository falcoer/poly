# Poly roadmap

The roadmap is executable: each milestone has a bounded scope, observable
acceptance criteria, mandatory automated checks, and an immutable annotated tag.

Status values are `pending`, `in-progress`, `implemented-awaiting-ci`,
`validated`, and `blocked`. The presence of the declared remote tag is the
authoritative evidence that CI validated its target commit.

## 0.1 — Canonical core and finite planning

- Status: `validated`
- Tag: `roadmap/0.1-core-model`
- Scope: immutable node/inventory, selection, action, constraint, proposal,
  plan, and diagnostic models; deterministic finite-plan negotiation.
- Acceptance:
  - providers are queried only for the requested verb;
  - competing claims are reported, never resolved by load order;
  - missing constraints block a plan without recursively adding actions;
  - identical inputs produce an identical plan identifier and action order.
- Checks: format, lint, strict typing, unit tests with at least 90% coverage,
  wheel and source distribution build.
- Excluded: driver discovery, command execution, persistent inventory.

## 0.2 — Driver SDK and conformance testkit

- Status: `validated`
- Tag: `roadmap/0.2-driver-sdk`
- Scope: versioned manifest, inspection/planning/execution protocols, registry,
  reusable fixtures, and driver conformance assertions.
- Acceptance:
  - built-in and external drivers share one public contract;
  - incompatible protocol versions are rejected with a useful diagnostic;
  - planning determinism and side-effect-free negotiation are testable.
- Checks: all 0.1 checks plus SDK compatibility and testkit self-tests.
- Excluded: process isolation and remote driver transport.

## 0.3 — Git reference driver

- Status: `validated`
- Tag: `roadmap/0.3-git-driver`
- Scope: discover local Git repositories and expose read-only `status` actions.
- Acceptance:
  - nested repositories are represented as distinct owned nodes;
  - branch, HEAD, cleanliness, and root metadata are observed;
  - inspection and negotiation do not modify repositories.
- Checks: all earlier checks plus fixture-backed Git integration tests.
- Excluded: commit, push, merge, and destructive worktree operations.

## 0.4 — Maven reference driver

- Status: `validated`
- Tag: `roadmap/0.4-maven-driver`
- Scope: inspect POMs, aggregators, GAVs, and local dependencies; negotiate
  reactor actions using the highest usable local aggregator and `-pl`/`-am`.
- Acceptance:
  - inheritance is distinguished from aggregation;
  - selected modules sharing a reactor become one action;
  - cross-reactor dependencies become explicit action constraints;
  - workspace materialization through a run-local repository is visible.
- Checks: all earlier checks plus multi-reactor planning fixtures.
- Excluded: full Maven effective-model parity and remote artifact publication.

## 0.5 — Executor, canonical reports, and CLI

- Status: `validated`
- Tag: `roadmap/0.5-runtime-reporting`
- Scope: sequential constraint executor, process adapter, result/event models,
  text/JSON/YAML/XML renderers, and initial `poly inspect/actions/plan/run` CLI.
- Acceptance:
  - an executor never mutates or extends the negotiated plan;
  - failure blocks dependants and produces complete action states;
  - current applicable, planned, and ready actions are distinguishable;
  - renderer outputs retain the same canonical meaning.
- Checks: all earlier checks plus end-to-end CLI smoke tests.
- Excluded: parallel execution and Web UI.

## 0.6 — Constructor, persistence, and control-plane

- Status: `validated`
- Tag: `roadmap/0.6-constructor-control-plane`
- Scope: `init`/`add` construction plans, versioned inventory/run persistence,
  and local/remote controller contracts.
- Acceptance: construction uses the common executor; plans and results resume
  as reports; controller capabilities are negotiated explicitly.
- Checks: migration, controller-contract, and recovery integration tests.
- Excluded: production hardening of untrusted third-party drivers.

## 0.7 — External driver kit

- Status: `validated`
- Tag: `roadmap/0.7-external-driver-kit`
- Scope: repository template, CI, packaging conventions, examples, and a
  dedicated development skill backed by the reusable conformance testkit.
- Acceptance: a fresh external driver can be generated, tested, packaged, and
  rejected when it violates the protocol without privileged core APIs.
- Checks: template generation and clean-room sample-driver CI.
- Excluded: public package-index release until an explicit release policy exists.


## Convergence correction

Milestones 0.1 through 0.7 validate the technical foundation declared in their
bounded scopes. They do not yet constitute acceptance of the original
end-to-end workspace-construction use case.

The normative target for authored workspace files and root-repository isolation
is [the workspace files contract](docs/reference/workspace-files.md). Milestones
0.8 through 0.12 implement that contract in dependency order. A milestone is
not complete because its internal API exists: every acceptance statement must
be demonstrated through its public CLI and persisted reports. No later feature
milestone may start before the 0.12 acceptance journey is validated.

Cross-milestone invariants:

- the root node owns and versions the composition;
- child repositories remain independent Git repositories, never implicit
  submodules and never tracked as content by the root repository;
- authored intent lives in `poly.yaml`, reproducible resolution in
  `poly.lock.yaml`, and disposable generated state below `.poly/`;
- one declared node keeps one stable identifier through all driver
  contributions and user-visible operations;
- every structural change is a planned, logged, reportable job action.

## 0.8 — Root-owned workspace contract and canonical identity

- Status: `implemented-awaiting-ci`
- Tag: `roadmap/0.8-workspace-manifest`
- Depends on: validated 0.7 baseline.
- Scope: implement the version 1 `poly.yaml` and `poly.lock.yaml` formats
  defined by the workspace files contract; compile them into generated state;
  reconcile declared nodes with driver observations; manage root Git isolation.
- Acceptance:
  - `poly.yaml` resides at the root node and is the only authored source of
    workspace composition;
  - the manifest explicitly represents one root node, parent/child topology,
    repository boundaries, technical modules, stable identifiers, relative
    paths, Git source declarations, requested refs, and optional natures;
  - `poly.lock.yaml` maps child source-node identifiers to immutable resolved
    commits and carries a canonical manifest digest without locking the root
    repository inside itself;
  - repository nodes and technical module nodes remain distinct concepts;
  - generated `.poly/state/workspace.json` and inventory documents are fully
    rebuildable and never contain indispensable authored intent;
  - Git, Maven, and later inspectors enrich the declared node rather than
    creating an unrelated competing identity;
  - observed undeclared repositories use deterministic identifiers and an
    explicit `observed-only` state without modifying the manifest;
  - `init` creates or reconciles a delimited Poly-managed root
    `.gitignore` block containing `/.poly/` and exact child-repository paths;
  - `add` and node removal update only that managed block, preserve all
    user-owned ignore rules, and never ignore `poly.yaml` or
    `poly.lock.yaml`;
  - manifest, lock, state, and ignore-file writes are atomic, deterministic,
    idempotent, and leave actionable diagnostics on failure;
  - malformed schemas, unknown fields, duplicate identifiers, path collisions
    (including case-insensitive Windows collisions), graph cycles, path escapes,
    stale locks, malformed ignore markers, and embedded credentials fail before
    any structural action.
- Checks: normative YAML fixtures and schema validation; YAML round-trip tests
  preserving comments/order where files are edited; manifest canonicalization
  and digest tests; tree and path-safety property tests; declared/observed
  identity tests; generated-state deletion/rebuild test; `.gitignore`
  creation/reconciliation/preservation/idempotence tests on Windows and Linux;
  migration or explicit rejection tests for provisional
  `.poly/workspace.json`.
- Demonstration: create a root manifest with two Git repository nodes and one
  nested Maven module, compile it twice, delete `.poly/`, rebuild it, and show
  equivalent canonical inventories while the root `git status` exposes only
  authored composition changes.
- Excluded: cloning or checking out child sources, which belongs to 0.10.

## 0.9 — Unified jobs and verb-first CLI

- Status: `pending`
- Tag: `roadmap/0.9-unified-jobs-cli`
- Depends on: 0.8 manifest compilation and stable identities.
- Scope: make construction participate in normal driver negotiation and expose
  driver verbs directly through `poly <verb>`.
- Acceptance:
  - `init`, `add`, and lock reconciliation are ordinary negotiated jobs with
    frozen plans, action dependencies, controller capabilities, logs, reports,
    and resumable state;
  - the constructor is a system driver using the same public proposal,
    planning, and execution contracts as other drivers;
  - no private `ConstructionPlanner` CLI path bypasses common negotiation;
  - `poly <verb>` negotiates and executes by default, including
    `poly status`, `poly verify`, `poly init`, and `poly add`;
  - `--plan` produces the same frozen plan without execution, while
    `poly plan <verb>` and `poly run <verb>` remain optional expert/CI
    façades over the same application service;
  - typed convenience options such as `poly add <id> --repo ... --ref ...`
    translate into the same canonical job request as generic parameters;
  - management commands `inspect`, `drivers`, `controllers`, and `report`
    are reserved; driver verbs are resolved dynamically with collision
    diagnostics;
  - initialization can plan from an empty pre-workspace context and may expose
    bootstrap and hydration as phases of one parent job without allowing an
    executor to invent actions at runtime.
- Checks: direct/expert CLI equivalence, reserved-name and collision tests,
  empty-context construction, multiple-driver contribution, phase/dependency
  reporting, resumption, and proof that planning is side-effect free.
- Demonstration: plan and execute the same `add` request through direct and
  expert forms and compare plan identifiers, actions, logs, and final report.
- Excluded: Git clone/fetch/checkout implementation, which belongs to 0.10.

## 0.10 — Root bootstrap and recursive Git hydration

- Status: `pending`
- Tag: `roadmap/0.10-git-materialization`
- Depends on: 0.8 workspace contract and 0.9 unified jobs.
- Scope: restore the original Polyrepo Studio use case: bootstrap or adopt one
  root control repository, then automatically hydrate every Git-backed
  descendant declared by its committed manifest and lock.
- Acceptance:
  - `poly init <root-repository> <target> [--ref <ref>]` clones or safely
    adopts the root node, then reads the exact committed `poly.yaml` and
    `poly.lock.yaml` it owns;
  - bootstrap and hydration are visible phases of one reportable `init` job;
    the second frozen plan is derived only after the root manifest is available
    and is recorded before child side effects begin;
  - every declared Git-backed descendant is restored automatically; no repeated
    `poly add` is required after cloning the root repository;
  - hydration follows the declared parent topology, supports nested independent
    repositories, and never creates or requires Git submodules;
  - the Git driver exposes clone, safe adoption, explicit fetch when permitted,
    ref resolution, checkout, and final HEAD verification as separate actions;
  - the lock wins during normal restoration: branch or tag intent is resolved
    to and verified against the recorded immutable commit;
  - an explicit update/lock operation is the only normal route that advances a
    moving reference and atomically changes `poly.lock.yaml`;
  - `poly add <id> --repo <url> --ref <ref> --path <path>` edits the manifest,
    resolves the lock, reconciles `.gitignore`, materializes, inspects, and
    reports the same node as one composite job;
  - `poly add <id> --path <existing-path>` validates and adopts an existing
    checkout without cloning or silently changing it;
  - rerunning a satisfied hydration is a no-op with an equivalent inventory;
    mismatched URLs/commits, dirty worktrees, non-empty targets, missing
    credentials, partial clones, stale locks, and interrupted jobs produce
    explicit policy diagnostics rather than destructive implicit repair;
  - a root-level `git add .` and commit never stages child repository content,
    while changes to `poly.yaml`, `poly.lock.yaml`, and the managed
    `.gitignore` block remain visible.
- Checks: local bare root and child remotes; branch/tag/SHA lock resolution;
  fresh root bootstrap; existing-root and child adoption; multi-level topology;
  restore without `add`; dirty/mismatch/non-empty/partial/interruption cases;
  idempotence and recovery; root Git index isolation; Windows/Linux paths.
- Demonstration: from an empty directory, initialize from a root repository
  containing only composition files, restore at least two independent child
  repositories, verify exact locked commits, modify a child, and prove the root
  repository neither stages nor commits that child modification.
- Excluded: commit, push, merge, and publication workflows for child
  repositories.

## 0.11 — Runtime driver lifecycle and inventory

- Status: `pending`
- Tag: `roadmap/0.11-driver-runtime`
- Depends on: 0.9 common runtime; integration is exercised against the hydrated
  workspace delivered by 0.10.
- Scope: connect built-in, system, and installed external drivers to the actual
  runtime and make their state observable.
- Acceptance:
  - the production registry loads validated `poly.drivers` entry points in a
    deterministic order alongside built-in and system drivers;
  - an installed conformant external driver enriches existing canonical nodes,
    proposes actions, and executes through `poly <verb>` without private core
    imports;
  - `poly drivers` lists name, version, origin, protocol version,
    capabilities, contributed verbs, load status, and rejection diagnostics;
  - duplicate identities, incompatible protocols, import failures, and verb
    collisions are isolated and never make load order decide behavior;
  - driver discovery and contributions appear in canonical machine-readable
    reports and remain stable across entry-point enumeration order.
- Checks: installed-wheel execution on a 0.10 hydrated workspace, rejection and
  isolation fixtures, shuffled entry-point ordering, duplicate/collision
  diagnostics, and text/JSON/YAML/XML parity.
- Demonstration: install the generated sample driver wheel, list it, use its
  direct verb against a declared node, and retrieve its actions and logs through
  the normal job report.
- Excluded: operating-system sandboxing of hostile code and public package-index
  publication.

## 0.12 — Clean-workstation functional acceptance

- Status: `pending`
- Tag: `roadmap/0.12-functional-baseline`
- Depends on: validated 0.8, 0.9, 0.10, and 0.11. This is a release gate, not a
  documentation-only milestone.
- Scope: prove the original minimum Poly journey on clean Windows and Linux
  environments and publish the exact reviewable build.
- Acceptance:
  - CI retains wheel and source distribution artifacts built from the exact
    validated commit, with checksums and version metadata;
  - a reviewer installs that wheel without cloning Poly's source;
  - from an empty directory and a root repository URL, one `poly init`
    restores committed `poly.yaml`/`poly.lock.yaml`, the managed
    `.gitignore`, multiple independent child repositories, and a multi-module
    Maven reactor at their locked commits;
  - `poly drivers`, `poly inspect`, `poly status`, and `poly verify`
    operate on the same stable identifiers declared in the root manifest;
  - init and verification reports expose phases, action logs, driver ownership,
    resolved commits, failures, and recovery through `poly report <run-id>`;
  - deleting `.poly/` and re-running reconstruction loses no composition
    information and yields an equivalent canonical inventory;
  - repeating hydration produces no unintended filesystem, Git-index, manifest,
    lock, or ignore changes;
  - changing a child worktree does not dirty the root repository, while changing
    a composition file does;
  - README provides copy-paste PowerShell and POSIX journeys using the retained
    package artifact and the same checked-in acceptance fixture.
- Checks: clean GitHub Actions Windows/Linux matrix; packaged-wheel installation;
  root bootstrap plus recursive Git hydration; Maven execution; external driver
  loading; report recovery; generated-state deletion; idempotence; root/child
  Git isolation; documentation command smoke tests.
- Evidence retained by CI: package artifacts and checksums, acceptance reports
  in all supported formats, action logs, final canonical inventory, root and
  child Git status snapshots, and the exact fixture commit identifiers.
- Excluded: Web UI, parallel execution, child commit/push/merge, remote package
  publication, and production sandbox hardening.
