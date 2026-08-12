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
end-to-end workspace-construction use case. Milestones 0.8 through 0.12 close
the functional gaps identified during the first user review. No later feature
milestone may start before the 0.12 acceptance journey is validated.

## 0.8 — Declarative workspace and canonical module identity

- Status: `pending`
- Tag: `roadmap/0.8-workspace-manifest`
- Scope: a user-authored, versioned `poly.yaml` manifest; schema validation;
  strict separation between desired workspace composition and generated
  `.poly` state; reconciliation of declared modules with driver observations.
- Acceptance:
  - `poly.yaml` is sufficient to describe stable module identifiers, paths,
    source declarations, requested references, and optional declared natures;
  - generated inventories, plans, runs, and logs remain JSON documents below
    `.poly` and never become the authored source of truth;
  - Git, Maven, and later inspectors enrich the declared module rather than
    creating unrelated competing identities;
  - one module keeps the user-selected identifier across construction,
    inspection, selection, planning, execution, and reporting;
  - undeclared repositories may still be discovered with deterministic
    generated identifiers and an explicit observed-only status;
  - malformed manifests, duplicate identifiers/paths, path escapes, and
    unsupported schema versions fail before any structural action.
- Checks: YAML/schema fixtures, declared/observed reconciliation tests,
  identity-stability tests, and migration or explicit rejection tests for the
  provisional `.poly/workspace.json` format.
- Excluded: remote source materialization, which belongs to 0.10.

## 0.9 — Unified jobs and verb-first CLI

- Status: `pending`
- Tag: `roadmap/0.9-unified-jobs-cli`
- Scope: make construction participate in normal driver negotiation and expose
  driver verbs directly through `poly <verb>`.
- Acceptance:
  - `init` and `add` are ordinary negotiated jobs with frozen plans,
    actions, controller capabilities, logs, reports, and resumable state;
  - the constructor is a system driver using the same public planning and
    execution contracts as other drivers;
  - the CLI contains no private `ConstructionPlanner` path that bypasses
    driver proposal and plan negotiation;
  - `poly <verb>` negotiates and executes by default, including
    `poly status`, `poly verify`, `poly init`, and `poly add`;
  - `--plan` exposes the frozen plan without execution, while
    `poly plan <verb>` and `poly run <verb>` may remain stable expert/CI
    forms over exactly the same application service;
  - management commands such as `inspect`, `drivers`, `controllers`, and
    `report` are reserved and verbs from drivers are resolved dynamically;
  - initialization can negotiate from an empty pre-workspace context.
- Checks: equivalence tests between direct and expert CLI forms, construction
  negotiation tests with multiple contributing drivers, report/log tests, and
  tests proving that planning is side-effect free.
- Excluded: Git clone/fetch/checkout implementation, which belongs to 0.10.

## 0.10 — Git materialization and workspace hydration

- Status: `pending`
- Tag: `roadmap/0.10-git-materialization`
- Scope: Git construction capabilities for creating a complete workspace from
  `poly.yaml` and for adding remote or already-present repositories.
- Acceptance:
  - `poly init` can hydrate every Git-backed module declared by a manifest;
  - `poly add <id> --repo <url> --ref <ref> --path <path>` declares,
    materializes, inspects, and reports one module as one job;
  - `poly add <id> --path <existing-path>` validates and adopts an existing
    checkout without cloning or silently changing it;
  - clone, fetch when explicitly required, reference resolution, checkout, and
    final HEAD verification are separate visible Git-driver actions;
  - branches, tags, and immutable commit SHAs are supported and the resolved
    commit is recorded in the canonical report;
  - rerunning a satisfied job is idempotent, while non-empty targets, mismatched
    remotes or references, dirty worktrees, and partial clones produce explicit
    policy diagnostics instead of destructive implicit repair;
  - constructor and Git actions declare dependencies and rollback/recovery
    boundaries without hiding filesystem side effects;
  - nested repositories remain independent modules and no Git submodule is
    introduced implicitly.
- Checks: local bare-remote fixtures with branch/tag/SHA hydration, existing
  checkout adoption, dirty/mismatch/partial-failure cases, idempotence, recovery,
  and Windows/Linux path behavior.
- Excluded: commit, push, merge, and publication workflows.

## 0.11 — Runtime driver lifecycle and inventory

- Status: `pending`
- Tag: `roadmap/0.11-driver-runtime`
- Scope: connect built-in, system, and installed external drivers to the actual
  runtime and make their state observable.
- Acceptance:
  - the production registry loads validated `poly.drivers` entry points in a
    deterministic order in addition to built-in and system drivers;
  - an installed conformant external driver can inspect, propose, and execute
    through the normal `poly` CLI without private core imports;
  - `poly drivers` lists name, version, origin, protocol version,
    capabilities, contributed verbs, and load status;
  - rejected, incompatible, duplicate, or failing drivers are isolated and
    reported with actionable diagnostics;
  - driver discovery results are included in canonical machine-readable
    reporting and do not vary with entry-point enumeration order.
- Checks: installed-wheel integration tests, successful external-driver
  end-to-end execution, rejection/isolation fixtures, deterministic listing,
  and text/JSON/YAML/XML rendering parity.
- Excluded: operating-system sandboxing of hostile driver code and public
  package-index publication.

## 0.12 — Workstation acceptance and reviewable distribution

- Status: `pending`
- Tag: `roadmap/0.12-functional-baseline`
- Scope: prove the original minimum Poly journey on clean Windows and Linux
  environments and make the exact validated package directly installable for
  user review.
- Acceptance:
  - CI publishes the wheel and source distribution built from the exact
    validated commit as retained downloadable artifacts;
  - a reviewer can install the validated build without cloning Poly's source;
  - from an empty target directory and one `poly.yaml`, `poly init`
    materializes a workspace containing multiple Git repositories and a
    multi-module Maven reactor;
  - `poly drivers`, `poly inspect`, `poly status`, and `poly verify`
    operate on the same stable module identifiers;
  - construction and verification jobs can be recovered with
    `poly report <run-id>`, including action logs and resolved Git commits;
  - repeating hydration produces no unintended changes and an equivalent
    canonical inventory and plan;
  - the README contains one copy-paste PowerShell journey and one POSIX-shell
    journey exercising the released artifact rather than a source checkout.
- Checks: clean-machine GitHub Actions matrix, packaged-wheel installation,
  end-to-end manifest hydration, Git plus Maven execution, report recovery,
  idempotence, and documentation smoke tests.
- Excluded: Web UI, parallel execution, full Git write lifecycle, remote package
  publication, and production sandbox hardening.
