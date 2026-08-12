---
name: poly-driver-development
description: Build, extend, review, or repair external Poly technology drivers and their repositories. Use when generating a poly-driver-* project, implementing inspectors/planners/handlers, updating poly-driver.toml or poly.drivers entry points, or running Poly driver conformance and packaging checks.
---

# Poly Driver Development

Build drivers exclusively against Poly's public SDK and prove their behavior
through the reusable black-box testkit.

## Workflow

1. Read repository instructions, `pyproject.toml`, `poly-driver.toml`, existing
   providers, fixtures, and tests. Read [the contract](references/contract.md).
2. For a new repository, run `poly driver new <technology> --path <target>` and
   work inside the generated project. Use `--poly-source <checkout>` only while
   deliberately testing an unreleased local Poly version.
3. Keep one `driver()` factory as the source of truth for both the manifest and
   `poly.drivers` entry point. Import only `poly.driver`,
   `poly.driver.testkit`, and `poly.model` public APIs.
4. Make inspection and planning immutable, deterministic, and side-effect free.
   Propose a finite action list for the requested verb only. Express missing
   facts as constraints or diagnostics; never infer prerequisite verbs.
5. Put side effects only in a complete action command or an `ActionHandler`.
   Declare requested-node coverage, exclusive claims, structural changes, and
   controller capability explicitly.
6. Add realistic fixture tests. Do not weaken conformance assertions, strict
   typing, lint rules, or coverage to make an implementation pass.
7. Run `poly-driver-test validate`, `inspect`, and `determinism`, then Ruff,
   mypy, pytest, and `uv build`. Fix protocol violations before packaging.

Stop and explain the incompatibility if the requested technology requires a
core protocol change, private API access, an inferred verb, or an unsafe hidden
side effect.
