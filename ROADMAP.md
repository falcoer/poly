# Poly roadmap

The roadmap is executable: each milestone has a bounded scope, observable
acceptance criteria, mandatory automated checks, and an immutable annotated tag.

Status values are `pending`, `in-progress`, `implemented-awaiting-ci`,
`validated`, and `blocked`. The presence of the declared remote tag is the
authoritative evidence that CI validated its target commit.

## 0.1 — Canonical core and finite planning

- Status: `implemented-awaiting-ci`
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

- Status: `pending`
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

- Status: `pending`
- Tag: `roadmap/0.3-git-driver`
- Scope: discover local Git repositories and expose read-only `status` actions.
- Acceptance:
  - nested repositories are represented as distinct owned nodes;
  - branch, HEAD, cleanliness, and root metadata are observed;
  - inspection and negotiation do not modify repositories.
- Checks: all earlier checks plus fixture-backed Git integration tests.
- Excluded: commit, push, merge, and destructive worktree operations.

## 0.4 — Maven reference driver

- Status: `pending`
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

- Status: `pending`
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

- Status: `pending`
- Tag: `roadmap/0.6-constructor-control-plane`
- Scope: `init`/`add` construction plans, versioned inventory/run persistence,
  and local/remote controller contracts.
- Acceptance: construction uses the common executor; plans and results resume
  as reports; controller capabilities are negotiated explicitly.
- Checks: migration, controller-contract, and recovery integration tests.
- Excluded: production hardening of untrusted third-party drivers.

## 0.7 — External driver kit

- Status: `pending`
- Tag: `roadmap/0.7-external-driver-kit`
- Scope: repository template, CI, packaging conventions, examples, and a
  dedicated development skill backed by the reusable conformance testkit.
- Acceptance: a fresh external driver can be generated, tested, packaged, and
  rejected when it violates the protocol without privileged core APIs.
- Checks: template generation and clean-room sample-driver CI.
- Excluded: public package-index release until an explicit release policy exists.
