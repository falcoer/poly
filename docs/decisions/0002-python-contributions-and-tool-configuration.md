# ADR 0002 — Python contributions and workspace tool configuration

> Update 2026-09-10: lifecycle and command decisions are superseded by
> [configuration nodes and hydration](../architecture/configuration-hydration.md).
> Real Eclipse import remains pending; the navigation prototype has been removed.

Date: 2026-09-09
Status: accepted direction; API details marked open below are not implemented decisions.

## Implementation follow-up — 0.13.1

The baseline descriptions and open questions below record the original decision.
The [implemented contracts](../architecture/contribution-contracts.md) resolve
initial/alternative producer semantics and add the minimal blueprint data contract
through Extension API 1.1. Facade string-map compatibility is preserved; generic
CLI binding and generated-file lifecycle remain future work.

## Context

Poly 0.13.0.1 is the validated baseline. Its mature behavior, Windows support,
parallel executor, inspection cache, and diagnostics represent work to preserve.
The user deferred Rust migration because other priorities have greater value.
This decision supersedes the active Rust gate and parity-baseline objective in
the earlier architecture note and the former 0.13.1 scope.

Future value includes preparing Eclipse, OpenCode, VS Code, and GitLab from the
workspace, plus the previously requested creation of an Angular application in
an existing empty GitLab repository. The earlier voice discussion could not be
retrieved; no historical argument is attributed to it here. The decisions below
record the explicit discussion of 2026-09-09 and the inspected baseline.

## Decisions

### Keep three contribution kinds, with different responsibilities

A plugin is the discovery/versioning container, not a fourth execution role.

| Contribution | Responsibility | Current public entry points |
| --- | --- | --- |
| Driver | Observe/qualify nodes, assess applicability, propose technology actions, optionally handle execution | inspect(context), propose(request), execute(action, context) |
| Facade | Translate user arguments into normalized command intent | translate(FacadeRequest) currently returns dict[str, str] |
| Blueprint | Describe a reusable, parameterized desired structure/configuration | Currently only name and description; registration/lookup, no application engine |

Driver interfaces are optional capabilities. Process actions can use Poly's
runner without a custom execute handler. Generation is an operation using
propose/execute, not a required new generate method or a new contribution kind.
A projection names the result of generation for a target tool.

A facade must not generate files, construct a private scheduler, or invoke another
driver imperatively. A blueprint must remain declarative rather than duplicate a
driver's generator. A driver may be useful without either a facade or blueprint;
a blueprint may concern one or several technologies. Packaging several
contributions together does not require separate repositories for each.

### Preserve domain-owned qualification and applicability

Inspectors return observed nodes, natures, metadata, and relations. Poly
reconciles these with authored declarations. Declared and observed natures may
coexist; observed qualification must not silently rewrite poly.yaml.

Poly selects planning providers by verb. Each provider's propose(request)
evaluates selected nodes' natures, parameters, metadata, relations, and available
context, returning actions and/or explained rejections. There is no mandatory
central verb-by-nature election table and no new supports() protocol.

This admits creation of not-yet-existing structures, aggregate Maven reactor
actions, heterogeneous IDE configurations, and multiple providers contributing
to one verb. Manifest nature lists describe the driver; they are not currently
an exhaustive eligibility filter. Nature names do not by themselves prove all
operational prerequisites.

Poly then validates the proposed actions, conflicts, and prerequisites and freezes
the finite plan. RejectedCandidate.missing is diagnostic information; it is not
an action requires set and must not trigger implicit work.

### Preserve finite fact-based prerequisites

ActionSpec.requires lists run-local facts needed before admission.
ActionSpec.produces lists facts made available only after success.
PlanningRequest.initial_constraints supplies initially available facts.
Constraint keys are serializable facts, not executable predicates or expressions.

All required facts must be available for an action to start. Missing producers
and dependency cycles are diagnosed before execution. Failure does not produce
success facts; unrelated work can continue. Execution resources prevent runtime
overlap; claims describe conflicting operation ownership. Neither is a substitute
for a causal prerequisite.

Providers must propose the necessary finite work for the requested verb.
The planner does not recursively discover another verb, implicitly install tools,
or expand the plan at runtime. A prepared journal uses the existing resolution
mechanism; blueprint expansion must finish before freezing its plan.

Facts are monotonic for one run and are not durable claims that the external
world remains unchanged. Handlers still check changing conditions when needed.
A prerequisite's producer must establish the fact it advertises; Poly does not
independently infer success from the key's name.

### Prepare tools through driver-generated configurations

Eclipse, VS Code, OpenCode, and GitLab drivers own their target formats.
Shared contracts cover declared outputs, intended mutations, configuration
ownership, collision diagnostics, and safe regeneration; they do not move each
tool's schema or merge rules into the engine.

Distinguish generated files, user-owned files, and explicitly managed sections.
Preview intended changes before applying them. Unchanged regeneration must not
create needless diffs. Detect intervening edits and conflicting generators;
never silently overwrite unrelated customization.

Separate shared repository configuration from machine-local preferences and
secret references. Do not bake credentials into templates or canonical reports.
Persist shared blueprint identity/version and parameters when needed for
reproducibility; .poly remains disposable and cannot be the only source of
authored intent. Exact persistence format is an open design decision.

GitLab configuration generation is local file generation. Creating/updating
remote projects or applying settings is a separate operation with explicit
scope. Cloning a GitLab-hosted repository already belongs to the Git driver.

## Known baseline gaps and bounded questions

1. Facades are discovered generically but CLI binding currently targets add.
   Generalize only enough for actual tool-preparation/creation journeys.
   Decide whether the current string-map result suffices before introducing a
   structured request result; preserve existing facade compatibility.
2. BlueprintContribution has no parameter schema, definition payload, or
   application contract. Define a minimal data-only shape and core-owned
   interpretation on one concrete configuration example; do not add execute().
3. Qualifying declared versus observed natures needs clear public semantics,
   including what removing an authored nature means if inspection redetects it.
   Add provenance storage only if an evidenced use requires it.
4. Clarify silent non-applicability versus actionable rejection, especially for
   heterogeneous selections and multiple providers.
5. Audit initial facts and multiple producers: the current planner adds graph
   edges to all producers, whereas runtime readiness uses available facts.
   Establish intended semantics and focused tests before any correction. Cover
   externally seeded cycles, self-dependency, alternate producers, genuine
   cycles, and failure. Do not silently introduce producer election.
6. Python contexts expose Path and model objects. The contract is not a security
   sandbox or a finished wire protocol; no IPC project is implied.
7. Generated configuration lifecycle details (merge policy, safe removal,
   provenance, stale-plan protection) are to be specified and exercised in
   0.13.2. Global rollback is not promised.

## Consequences and validation

Keep Python and the existing public SDK compatibility. Freeze only justified
contracts, not every incidental implementation detail. Use independent plugin
fixtures to prove that useful generation needs no privileged core imports.
Reuse existing conformance, Windows/Linux acceptance, quality, and performance
checks, extending them only for concrete gaps.

Implement in the order recorded in [ROADMAP.md](../../ROADMAP.md).
The previous Rust study is retained as historical context, with no active gate,
date, port, transport, or cross-implementation runner.
