# Poly roadmap

This file is the compact milestone index. Detailed scope, acceptance criteria,
evidence, and exclusions belong in the linked release documents.

Statuses are `pending`, `in-progress`, `implemented-awaiting-validation`, and
`validated`. A `validated` milestone requires explicit real-use acceptance, a
green complete CI run, and an annotated tag on the accepted commit. Later
success does not silently validate an earlier milestone.

## Durable product invariants

- the root repository owns composition and versioning;
- child repositories remain independent Git repositories;
- `poly.yaml` is authored, `poly.lock.yaml` is reproducible, and `.poly/` is disposable;
- node, contribution, plan, action, event, and report identities are stable;
- Poly alone owns planning, scheduling, interruption, reporting, and rendering;
- every structural change is finite, planned, observable, and reportable.

## 0.1 — Canonical core and finite planning

- Status: `validated`
- Tag: `roadmap/0.1-core-model`
- Summary: canonical graph, constraints, claims, actions, plans, and deterministic negotiation. [Details](docs/releases/0.1-0.10.md#01--canonical-core-and-finite-planning)

## 0.2 — Driver SDK and conformance testkit

- Status: `validated`
- Tag: `roadmap/0.2-driver-sdk`
- Summary: public driver contracts and reusable conformance tests. [Details](docs/releases/0.1-0.10.md#02--driver-sdk-and-conformance-testkit)

## 0.3 — Git reference driver

- Status: `validated`
- Tag: `roadmap/0.3-git-driver`
- Summary: reference Git inspection, planning, execution, and verification. [Details](docs/releases/0.1-0.10.md#03--git-reference-driver)

## 0.4 — Maven reference driver

- Status: `validated`
- Tag: `roadmap/0.4-maven-driver`
- Summary: reference Maven inspection, planning, execution, and verification. [Details](docs/releases/0.1-0.10.md#04--maven-reference-driver)

## 0.5 — Executor, canonical reports, and CLI

- Status: `validated`
- Tag: `roadmap/0.5-runtime-reporting`
- Summary: sequential execution, canonical reports, and initial command-line surface. [Details](docs/releases/0.1-0.10.md#05--executor-canonical-reports-and-cli)

## 0.6 — Constructor, persistence, and control-plane

- Status: `validated`
- Tag: `roadmap/0.6-constructor-control-plane`
- Summary: workspace construction, persistence, and control-plane ownership. [Details](docs/releases/0.1-0.10.md#06--constructor-persistence-and-control-plane)

## 0.7 — External driver kit

- Status: `validated`
- Tag: `roadmap/0.7-external-driver-kit`
- Summary: external driver packaging and conformance workflow. [Details](docs/releases/0.1-0.10.md#07--external-driver-kit)

## 0.8 — Root-owned workspace contract and canonical identity

- Status: `validated`
- Tag: `roadmap/0.8-workspace-manifest`
- Summary: root-owned manifest/lock contract and stable workspace identity. [Details](docs/releases/0.1-0.10.md#08--root-owned-workspace-contract-and-canonical-identity)

## 0.9 — Unified jobs and verb-first CLI

- Status: `validated`
- Tag: `roadmap/0.9-unified-jobs-cli`
- Summary: unified job model and verb-first CLI. [Details](docs/releases/0.1-0.10.md#09--unified-jobs-and-verb-first-cli)

## 0.10 — Root bootstrap and recursive Git hydration

- Status: `validated`
- Tag: `roadmap/0.10-git-materialization`
- Summary: root bootstrap and recursive materialization of locked repositories. [Details](docs/releases/0.1-0.10.md#010--root-bootstrap-and-recursive-git-hydration)

## 0.10.1 — Daily workspace authoring and CLI clarity

- Status: `validated`
- Tag: `roadmap/0.10.1-daily-workflow`
- Summary: lightweight repository authoring and clearer daily interaction. [Details](docs/releases/0.10.1.md)

## 0.10.2 — Runtime output and release identity corrections

- Status: `validated`
- Tag: `roadmap/0.10.2-runtime-corrections`
- Summary: streaming output corrections and trustworthy package identity. [Details](docs/releases/0.10.2.md)

## 0.11 — Runtime driver lifecycle and inventory

- Status: `validated`
- Tag: `roadmap/0.11-driver-runtime`
- Summary: installed driver discovery, lifecycle, isolation, and inventory. [Details](docs/releases/0.11.0.md)

## 0.12 — Clean-workstation functional acceptance

- Status: `validated`
- Tag: `roadmap/0.12-functional-baseline`
- Summary: packaged end-to-end acceptance on clean Windows and Linux hosts. [Details](docs/releases/0.12.0.md)

## 0.12.1 — Stable interactive CLI presentation

- Status: `validated`
- Tag: `roadmap/0.12.1-interactive-cli`
- Summary: stable interactive hierarchy without changing canonical reports. [Details](docs/releases/0.12.1.md)

## 0.12.2 — Prepared plans and driver-contributed add façades

- Status: `validated`
- Tag: `roadmap/0.12.2-prepared-plans-v2`
- Summary: durable prepared plans and façade contributions resolved by stable identity. [Details](docs/releases/0.12.2.md)

## 0.12.3 — Deferred command preparation and planned UX

- Status: `validated`
- Tag: `roadmap/0.12.3-deferred-command-preparation`
- Summary: immediate command journaling and one frozen whole-plan resolution at execution. [Details](docs/releases/0.12.3.md)

## 0.12.4 — Interactive rendering and Git hydration corrections

- Status: `validated`
- Tag: `roadmap/0.12.4-interactive-rendering-corrections`
- Summary: safe locked-commit hydration, clone-depth controls, timing, and rendering corrections. [Details](docs/releases/0.12.4.md)

## 0.12.5 — Terminal rendering modes and durable history

- Status: `validated`
- Tag: `roadmap/0.12.5-terminal-rendering-modes`
- Summary: compact single-owner `live`, `flow`, and structured rendering with durable history. [Details](docs/releases/0.12.5.md)

## 0.12.6 — Plugin extension architecture

- Status: `validated`
- Tag: `roadmap/0.12.6-plugin-extension-architecture`
- Summary: stable extension identities and registries while Poly retains orchestration ownership. [Details](docs/releases/0.12.6.md)

## 0.13 — Bounded parallel plan execution

- Status: `validated`
- Tag: `roadmap/0.13-bounded-parallel-execution`
- Summary: deterministic frontier scheduling, bounded workers, isolation, interruption, and canonical reports. [Details](docs/releases/0.13.0.md)

## 0.13.0.1 — Targeted execution performance and actionable diagnostics

- Status: `validated`
- Tag: `roadmap/0.13.0.1-targeted-execution-diagnostics`
- Summary: reusable deterministic inspection inventory, explicit targeted-build scope, grouped diagnostics, and actionable failed-action logs. [Details](docs/releases/0.13.0.1.md)

## Current direction

Python remains the maintained implementation; Rust and dedicated parity work are
deferred without a date. Future version assignments are provisional.
See [ADR 0002](docs/decisions/0002-python-contributions-and-tool-configuration.md)
and [the next-session handover](docs/handover/2026-09-09-next-step.md) for decisions,
backlog, delivery rules, and the 0.13.1 starting point.

## 0.13.1 — Contribution contracts and finite preconditions

- Status: `validated`
- Tag: `roadmap/0.13.1-contribution-contracts`
- Summary: consolidate driver qualification and applicability, facade normalization,
  a minimal declarative blueprint contract, and finite prerequisite semantics.
  Reuse existing tests and benchmarks; resolve evidenced gaps only.
  [Details](docs/releases/0.13.1.md)

## 0.13.2 — Configuration generation and Eclipse preparation

- Status: `pending`
- Planned tag: `roadmap/0.13.2-eclipse-configuration`
- Summary: establish configuration ownership and safe regeneration through a first
  useful Eclipse driver, using the public extension boundary.
  [Details](docs/releases/0.13.2.md)

## 0.13.3 — VS Code and OpenCode preparation

- Status: `pending`
- Planned tag: `roadmap/0.13.3-editor-configuration`
- Summary: reuse the configuration contract for VS Code and OpenCode; keep each
  tool's formats and behavior in its driver.
  [Details](docs/releases/0.13.3.md)

## 0.13.4 — GitLab CI configuration

- Status: `pending`
- Planned tag: `roadmap/0.13.4-gitlab-configuration`
- Summary: generate reviewable GitLab CI configuration consistent with explicit
  Poly workflows; remote project changes remain a separate scope.
  [Details](docs/releases/0.13.4.md)

## 0.13.5 — Angular creation through contributions

- Status: `pending`
- Planned tag: `roadmap/0.13.5-angular-blueprint`
- Summary: deliver the requested empty-repository-to-Angular journey using a
  facade, a versioned blueprint, and Node/Angular technology contributions.
  [Details](docs/releases/0.13.5.md)

