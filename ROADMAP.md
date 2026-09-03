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

- Status: `validated`
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

- Status: `validated`
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

- Status: `validated`
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


## 0.10.1 — Daily workspace authoring and CLI clarity

- Status: `validated`
- Tag: `roadmap/0.10.1-daily-workflow`
- Depends on: validated 0.10 Git materialization baseline.
- Scope: correct the daily authoring workflow before extending the driver
  runtime: keep declaration and locking lightweight, make hydration explicit,
  complete contextual nature management, and make interactive command results
  immediately readable.
- Implemented:
  - interactive text output is grouped by command with an action-oriented
    heading, indented plan and action details, and a framed final result;
  - successful, failed, and blocked actions are distinguished with graphical
    markers and terminal colors;
  - `-q`, default, `-v`, and `-vv` verbosity levels are available, with
    `--color auto|always|never` and `NO_COLOR` support;
  - JSON, YAML, and XML retain the unchanged canonical `poly.report/v1`
    document.
  - source-backed `add` resolves and atomically records intent and the exact
    lock commit without materializing a child worktree;
  - explicit `hydrate` performs locked clone/adoption, fetch, checkout, and
    verification and remains idempotent;
  - contextual, multi-value nature add/remove and alphabetic nature inventory
    are available from the nearest workspace;
  - built-in and system drivers are inventoried from an empty workspace.
- Acceptance validated by complete remote CI:
  - `poly add <id> --repo <url> --ref <selector> --path <path>` updates
    `poly.yaml`, resolves and atomically updates `poly.lock.yaml`, reconciles
    the managed `.gitignore` block, and reports the result without cloning,
    fetching, adopting, checking out, or otherwise materializing the child;
  - every successful source-backed `add` leaves a composition immediately
    ready for `poly hydrate`; resolution failure leaves no partial manifest,
    lock, state, or ignore change;
  - `poly hydrate` is the explicit normal command that materializes locked
    child repositories; root bootstrap may still expose recursive hydration as
    a documented phase of restoring a complete workspace;
  - selector intent remains in `poly.yaml` while `poly.lock.yaml` always
    records the exact resolved commit used by hydration;
  - `poly nature list` returns the available natures contributed by loaded
    drivers in alphabetical order;
  - contextual `poly nature add` and `poly nature remove` resolve the nearest
    workspace and current node, accept an explicit `.`, and support multiple
    natures in one command;
  - `poly drivers` exposes built-in and system drivers even for an empty
    workspace, with automated regression coverage.
- Checks: all 0.10 checks plus proof that source-backed `add` performs no child
  worktree side effect; atomic add failure; explicit hydration; repeated
  hydration idempotence; contextual and multi-value nature CLI tests; driver
  enumeration on an empty workspace; interactive rendering snapshots with and
  without colors; unchanged structured-report parity.
- Demonstration: generate and execute a series of `poly add` declarations for a
  large existing polyrepo model, commit only `poly.yaml`, `poly.lock.yaml`,
  and `.gitignore`, then explicitly hydrate the same composition in a clean
  target while retaining readable per-command results.
- Excluded: installed external-driver lifecycle, which remains 0.11; advanced
  tag-pattern/SemVer selector policies; parallel hydration; child
  commit/push/merge workflows.

## 0.10.2 — Runtime output and release identity corrections

- Status: `validated`
- Tag: `roadmap/0.10.2-runtime-corrections`
- Depends on: validated 0.10.1 daily workflow.
- Scope: package the runtime corrections made after 0.10.1 and expose an
  unambiguous installable version before beginning the 0.11 driver lifecycle.
- Implemented:
  - direct verbs stream action progress before their final completion block;
  - successful runs without actions render a neutral `NONE` result;
  - existing milestone tags are accepted only when their target remains an
    ancestor of the CI commit;
  - package metadata and `poly --version` both report `0.10.2` from one version
    source.
- Acceptance:
  - source and wheel metadata report version `0.10.2`;
  - `poly --version` prints `poly 0.10.2` without requiring a workspace;
  - version metadata cannot diverge from the public Python version;
  - the complete formatting, lint, typing, test, build, clean-room driver, and
    Windows/Linux workspace gates remain green.
- Excluded: installed external-driver lifecycle, which remains 0.11; any new
  workspace or driver capability.
- Validation:
  - the exact 0.10.2 boundary commit is `1c1346cb032b3429095091f173e5c6a5b766383c`;
  - dedicated GitHub Actions run `33598204087` checked out that exact commit and
    passed the Linux/Windows, formatting, lint, strict typing, coverage,
    clean-room external-driver, build, and 0.10.2 identity gates;
  - the remote immutable annotated tag `roadmap/0.10.2-runtime-corrections`
    targets exactly that commit. The later 0.11 CI was not used as a substitute
    for the missing 0.10.2 distribution-identity proof.

## 0.11 — Runtime driver lifecycle and inventory

- Status: `validated`
- Tag: `roadmap/0.11-driver-runtime`
- Depends on: 0.9 common runtime and the completed 0.10.2 correction baseline;
  integration is exercised against a hydrated workspace.
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
- Checks: installed-wheel execution on a 0.10.2 hydrated workspace, rejection and
  isolation fixtures, shuffled entry-point ordering, duplicate/collision
  diagnostics, and text/JSON/YAML/XML parity.
- Demonstration: install the generated sample driver wheel, list it, use its
  direct verb against a declared node, and retrieve its actions and logs through
  the normal job report.
- Excluded: operating-system sandboxing of hostile code and public package-index
  publication.
- Implemented:
  - production startup discovers installed entry points and inventories system,
    built-in, loaded installed, and rejected installed drivers;
  - all candidate factories are resolved before deterministic identity and verb
    arbitration, so enumeration order cannot select a winner;
  - installed inspectors enrich canonical declared nodes and their planners and
    handlers participate in ordinary direct-verb execution;
  - canonical inspection, action, plan, run, and driver reports carry driver
    identity, origin, protocol, capabilities, verbs, status, and diagnostics;
  - clean-room CI builds and installs the core and generated sample-driver wheels,
    exercises the direct verb, and reloads its persisted run report.
- Validation:
  - the complete Linux and Windows matrix passed on commit `c0fe778`;
  - 106 tests passed with 90.55% coverage, including deterministic rejection and
    canonical renderer parity;
  - GitHub Actions created the annotated tag
    `roadmap/0.11-driver-runtime` on the validated commit.

## 0.12 — Clean-workstation functional acceptance

- Status: `validated`
- Tag: `roadmap/0.12-functional-baseline`
- Depends on: validated 0.8, 0.9, 0.10, 0.10.1, 0.10.2, and 0.11. This is a release
  gate, not a documentation-only milestone.
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
- Validation:
  - functional merge commit: `a41159b93ccc3580dbfbbca17a85bf5c553726e5`;
  - GitHub Actions run `33623639390` passed quality, Ubuntu/Windows workspace contracts, deterministic fixture, external-driver clean-room, and POSIX/Windows clean-workstation acceptance;
  - retained distribution, quality, fixture, Linux acceptance, and Windows acceptance artifacts all report head SHA `a41159b93ccc3580dbfbbca17a85bf5c553726e5`;
  - immutable annotated tag `roadmap/0.12-functional-baseline` (tag object `2870e961b8e565751ab253934eac2ef49294768c`) targets exactly the functional merge commit.

## 0.12.1 — Stable interactive CLI presentation

- Status: `validated`
- Tag: `roadmap/0.12.1-interactive-cli`
- Depends on: validated 0.12 functional baseline.
- Scope: consolidate the interactive command block, replace transient action
  lines in place, expose useful execution timing, distinguish user intent
  visually from Poly-generated state, and establish the structured result
  channel required for safe parallel rendering without changing plan semantics.
- Acceptance:
  - the complete command block is delimited by horizontal separators starting
    at the terminal's left margin;
  - the user-request heading also starts at the left margin and uses the
    terminal's default foreground color rather than a forced ANSI white;
  - a source-backed add renders
    `ADDING <node-id> from <source-url> (ref: <requested-ref>) ...`, using the
    sanitized requested URL and selector rather than the resolved commit;
  - `PLAN` retains its generated-state color and indentation, while the final
    `SUCCESS`, `FAILURE`, or `NONE` line uses the same indentation as
    `PLAN`;
  - action rows remain one level below `PLAN`, with wrapped details one
    additional level below their action;
  - drivers, action handlers, and child processes never write to or reposition
    the interactive terminal directly; the runtime captures per-action stdout
    and stderr, and one serialized renderer owns all terminal writes;
  - a driver execution result may expose at most one concise scalar value for
    the action row and zero or more typed user-facing output references;
  - scalar values are single-line, control-free canonical data and render on
    their action row without turning arbitrary driver text into terminal output;
  - output references distinguish files from URLs and retain an optional label
    and media type in canonical reports;
  - only deliverables explicitly requested or exposed by the command are
    user-facing outputs; internal run files, captured logs, resolutions, and
    temporary artifacts are not promoted automatically;
  - user-facing outputs from all actions are collected deterministically below
    the final command result in one `OUTPUT` section, including valid
    diagnostic deliverables returned by a failed action;
  - file and URL entries use safe terminal hyperlinks when the interactive sink
    supports them and fall back to the same visible plain text in redirected,
    unsupported, or structured output;
  - terminal values, labels, paths, and URLs are sanitized against control
    characters, embedded credentials, and terminal-escape injection;
  - in an interactive terminal, each action occupies one stable visual row and
    its transient `RUNNING` state is replaced in place by `OK`, `KO`, or
    `BLOCKED`;
  - append-only output such as redirection and CI logs emits only terminal
    action states at normal verbosity and never emits cursor-control sequences;
  - every persisted run event carries an RFC 3339 UTC `occurred_at` timestamp,
    and action results expose `started_at`, `completed_at`, and
    `duration_ms`;
  - event sequence remains the total-order tie-breaker when timestamps are
    equal, and structured reports retain every planned, ready, running, and
    terminal event;
  - separators adapt to the usable terminal width with a deterministic fallback,
    and long identifiers or summaries never corrupt subsequent output;
  - failures, blocked actions, runner exceptions, and interruption leave the
    terminal in a clean state;
  - `-q`, `-v`, `-vv`, `--color`, and `NO_COLOR` retain their documented
    meaning, and JSON, YAML, and XML never contain terminal controls;
  - the interactive rendering state does not assume that only one action can be
    running, so it can support the bounded-parallel executor introduced in 0.13.
- Checks: terminal-capability abstraction tests; interactive replacement and
  synthetically interleaved multi-action event tests; proof that handlers and
  child processes cannot write directly to the terminal; isolated stdout/stderr
  capture; scalar-value rendering; deterministic output aggregation; safe file
  and URL hyperlink generation with plain-text fallback; control-character,
  credential, and escape-sequence sanitization; redirected-output and
  no-control-sequence tests; timestamp and duration tests; narrow and resized
  terminal cases; source-heading sanitization; Windows/Linux snapshots;
  interruption cleanup; structured-report parity.
- Demonstration: run a source-backed `poly add` plus driver commands returning
  a scalar value, a generated report file, and a report URL; compare interactive
  hyperlinks with redirected plain text, show one final row per action and one
  aggregated `OUTPUT` section, reload the persisted report, and correlate its
  timestamped action transitions.
- Excluded: execution parallelism itself, terminal dashboards, progress
  percentages, spinners, and historical report animation.

Validation evidence:

- GitHub Actions run `33722969218` passed quality, external-driver clean-room,
  Ubuntu/Windows workspace contracts, fixture construction, and POSIX/Windows
  clean-workstation acceptance on merge commit `3af030cb90c74318093f271df03a37fc2f80a0c5`;
- annotated tag `roadmap/0.12.1-interactive-cli` (tag object
  `a1335a77990abb0203f43d422b23e61f7dfc2b98`) targets that exact validated
  commit.

## 0.12.2 — Prepared plans and driver-contributed add façades

- Status: `validated`
- Tag: `roadmap/0.12.2-prepared-plans-v2`
- Field acceptance: completed 2026-09-03 on the `qc2-p17-poly` workspace;
  cumulative repository preparation and execution, add/remove behavior, boundary
  conditions, and driver discovery were accepted with 3 loaded drivers and
  0 rejected drivers.
- Depends on: validated 0.12.1 interactive CLI contract.
- Scope: let users compose several ordinary Poly commands into one frozen,
  persistent plan before execution, and make the specialized vocabulary of
  `poly add` an explicitly registered driver contribution rather than a closed
  engine-owned inventory.
- Acceptance:
  - every single-phase direct plannable command accepts `--prepare` in addition
    to the existing isolated `--plan` preview;
  - `--prepare` appends the normalized request and its frozen actions to the one
    current prepared plan without executing an action or modifying authored
    workspace files;
  - repeated preparation validates the complete action graph, including
    preserved provider diagnostics, duplicate action identifiers, claims,
    missing constraints, and cycles;
  - cross-command dependencies and overlapping structural mutations preserve
    authoring order through canonical constraints, while independent work
    remains eligible for bounded parallel execution;
  - `poly plan` renders the current prepared plan and `poly plan clean`
    idempotently removes only its disposable `.poly/` state;
  - the former expert syntax `poly plan <verb>` is removed, while
    `poly <verb> --plan` remains the non-cumulative one-command preview;
  - `poly exec` verifies that the authored workspace base has not changed and
    executes the exact persisted frozen plan without driver inspection,
    negotiation, or runtime action expansion;
  - successful execution consumes the current plan while preserving its normal
    historical run report; failed execution retains the prepared plan and its
    report for diagnosis;
  - a workspace has at most one current prepared plan and exposes no user-facing
    plan identifier selection or parallel plan catalog;
  - current-plan persistence reuses the canonical `poly.state/v1` envelope and
    `poly.report/v1` plan document rather than introducing a batch, script, or
    intention-file format;
  - immediate execution refuses to bypass an existing prepared plan, while
    isolated previews remain available;
  - `poly add <facade> ...` resolves façades from the deterministic driver
    registry, and the engine contains no enumeration of repository, module, or
    technology-specific add façades;
  - façade argument schemas and translation to canonical planning parameters
    are side-effect-free public driver contributions with useful dynamic help;
  - duplicate façade identities are rejected deterministically and façade
    inventory is visible through canonical driver reports;
  - built-in `module` and Git `repository` façades cover local modules, remote
    repositories, and safe adoption of existing Git worktrees;
  - the two-phase root-repository bootstrap rejects `--prepare` without side
    effects because its recursive hydration cannot be frozen before cloning;
- Checks: single and cumulative preparation; exact frozen-plan execution;
  current-plan display/clean/consumption; empty and stale states; blocked and
  failed plans; command/action collision and graph validation; no authored-file
  mutation before execution; canonical report round-trip and migration;
  removal of `poly plan <verb>`; facade discovery, dynamic help, translation,
  collision isolation, installed-driver compatibility, Windows/Linux paths,
  clean-room external-driver gates, and structured-renderer parity.
- Demonstration: prepare at least three source-backed repository additions with
  `poly add repository ... --prepare`, inspect their one combined plan, execute
  it with `poly exec`, and prove that all authored composition changes occur
  only during execution and that the retained run report describes the exact
  previously displayed plan.
- Excluded: concurrent action execution, multiple named prepared plans,
  runtime plan expansion, automatic stale-plan replanning, blueprint/template
  aggregation, pathless logical service nodes, and distributed execution.

The annotated tag `roadmap/0.12.2-prepared-plans` was created prematurely on
`630d349` before the asynchronous review completed. It is retained as immutable
historical evidence but is not authoritative for this milestone. The corrected
annotated tag `roadmap/0.12.2-prepared-plans-v2` is the validation authority.

## 0.12.3 — Deferred command preparation and planned UX

- Status: `pending`
- Tag: `roadmap/0.12.3-deferred-command-preparation`
- Depends on: validated and field-accepted 0.12.2 prepared-plan composition.
- Scope: make preparation an immediate recording of normalized command intent,
  present that state unambiguously as planned rather than successful, and defer
  workspace inspection and whole-graph action resolution to one `poly exec`
  phase.
- Acceptance:
  - `poly <verb> ... --prepare` validates CLI and façade arguments, then
    atomically appends one normalized command to the single current command
    journal without invoking inspectors, planners, handlers, or external
    systems;
  - preparation does not construct, persist, count, or render executable actions
    and its cost is independent of the number of actions that earlier commands
    would eventually produce;
  - the interactive result uses a magenta `○ PLANNED` status for the complete
    result block, names the command, reports singular/plural command count in the
    current plan, and reminds the user to run `poly exec`;
  - preparation never emits `SUCCESS`, `OK`, `executable`, or a changing
    plan fingerprint that could suggest creation of multiple user-selectable
    plans;
  - `poly plan` lists the normalized commands in authoring order and
    `poly plan clean` retains its idempotent disposable-state semantics;
  - `poly exec` snapshots and inspects the authored workspace once, resolves
    every recorded command into one globally validated action graph, persists
    that frozen graph before the first side effect, then executes exactly that
    graph;
  - overlapping structural changes preserve command order, dependencies created
    within the batch are resolvable, and independent actions remain eligible for
    the later bounded-parallel executor;
  - a resolution failure performs no authored or external mutation and retains
    the command journal plus diagnostics; successful execution consumes the
    journal and retains the historical frozen plan and run report;
  - structured JSON, YAML, and XML expose a canonical planned-command state
    equivalent to the interactive rendering;
  - a persisted 0.12.2 frozen prepared plan remains executable or cleanable after
    upgrade; appending a new command to that legacy plan is rejected with an
    actionable instruction rather than silently changing its semantics.
- Checks: provider call-count proof that preparation does not inspect or plan;
  cumulative command-journal persistence and round-trip; singular/plural and
  color-aware golden output; structured-renderer parity; one-shot global
  resolution; dependency and collision validation; failure atomicity; legacy
  0.12.2 plan compatibility; Windows/Linux paths; and a declared performance
  regression budget for large command batches.
- Demonstration: prepare a large repository batch while showing immediate
  `PLANNED` results and increasing command counts, inspect the command list,
  execute once, and prove that inspection and action-graph construction occur
  only during `poly exec`.
- Excluded: multiple named plans, concurrent preparation, automatic execution,
  runtime action expansion after the frozen graph is persisted, blueprint
  aggregation, and parallel action execution.

## 0.13 — Bounded parallel plan execution

- Status: `pending`
- Tag: `roadmap/0.13-bounded-parallel-execution`
- Depends on: validated 0.12.1 interactive CLI baseline and validated 0.12.2
  prepared-plan composition.
- Scope: execute independent actions from the same ready frontier concurrently,
  with deterministic frontier selection, explicit execution-resource isolation,
  and a worker limit bounded by the capabilities visible to the Poly process.
- Acceptance:
  - parallel execution never mutates, extends, or reinterprets the frozen plan;
  - at the start of each execution iteration, the executor freezes the
    canonically ordered frontier of actions whose required constraints are
    available;
  - only actions from that frontier may run concurrently; if the frontier is
    larger than the worker limit, its remaining actions stay queued, and the
    next frontier is not opened until every action in the current frontier has
    reached a terminal state;
  - `--jobs 1`, `--jobs <n>`, and `--jobs auto` are supported, with
    `--jobs 1` retaining the observable sequential 0.12.1 semantics;
  - automatic sizing respects the CPU entitlement or affinity visible to the
    process, never selects fewer than one worker, and has a conservative
    cross-platform fallback;
  - the requested and effective worker limits are recorded in the canonical run
    report and do not affect the plan identifier;
  - runtime resource declarations are distinct from planning
    `ActionClaim` ownership and prevent actions holding the same exclusive
    execution resource from overlapping;
  - structural actions and actions or driver handlers that do not declare
    concurrency safety remain conservatively serialized;
  - commands and handlers execute in action-isolated output contexts so their
    logs and details cannot overwrite one another;
  - a failed action produces no constraints and blocks only its dependants;
    already-running siblings and actions independent of the failure complete;
  - runner exceptions are contained per action and never abort result
    collection for the rest of the frontier;
  - action results retain canonical plan order, while timestamped events record
    actual causal start and completion order with a synchronized global
    sequence;
  - the interactive renderer maintains one stable row per running action and
    leaves only terminal rows when the frontier completes;
  - interruption stops admission of new actions, records the affected states,
    collects or terminates running work according to explicit policy, and leaves
    a reloadable run report.
- Checks: deterministic frontier tests; explicit resource-exclusion tests;
  controlled overlap tests without timing-only assertions; worker-limit and
  automatic-capacity tests; failure, exception, and interruption isolation;
  concurrent event sequencing and log separation; sequential compatibility;
  Windows/Linux execution; canonical renderer parity.
- Demonstration: prepare several independent repository additions, execute the
  displayed frozen plan concurrently while actions targeting the same
  repository remain serialized, then use timestamped reports to show the
  overlap and compare elapsed time with `--jobs 1`.
- Excluded: distributed scheduling, action preemption, adaptive CPU/memory or I/O
  weighting, speculative execution, driver-internal parallelism, and runtime
  plan expansion.
