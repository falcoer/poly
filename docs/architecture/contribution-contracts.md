# Contribution contracts — Poly 0.13.1

This is the implemented refinement of [ADR 0002](../decisions/0002-python-contributions-and-tool-configuration.md).
The maintained engine remains Python. There are three contribution kinds; a
projection is the output of a driver operation, not another contribution kind.

## Entry points and responsibility

| Concept | Implemented contract | Owner |
| --- | --- | --- |
| Plugin | `poly.plugins` factory → `PluginRegistration`, versioned `Plugin` descriptor | Discovery container |
| Driver role | Optional `inspect(context)`, `propose(request)`, `execute(action, context)` | Technology contribution |
| Driver capability | `inspect`, `plan`, `execute`, legacy `facade`; registration must match | Driver manifest |
| Verb | `PlanningProvider.verbs`; Poly asks only providers for the requested verb | Core selection |
| Nature | Driver-observed or authored qualification, such as `maven/project` | Driver interpretation |
| Facade | `translate(FacadeRequest) -> dict[str, str]`, `verb` names the canonical request | Input normalization |
| Blueprint | `BlueprintDefinition` data interpreted by `ContributionRegistry.resolve_blueprint` | Core validation of desired configuration |

Legacy `poly.drivers` factories and `DriverRegistration` remain supported through
implicit plugins. Identities remain `driver:<name>`, `facade:<verb>:<name>`, and
`blueprint:<name>`. API roles, declared capabilities, verbs, and natures are not
interchangeable. A process action needs no custom execute handler.

Driver and Extension APIs are now **2.0**. Configuration nodes can have no
filesystem path; older API 1.x plugins must be updated before loading. The
[configuration/hydration contract](configuration-hydration.md) records this
intentional compatibility break and the new optional driver contributions.

## Qualification and applicability

Inspectors return nodes, natures, metadata, and relations. `reconcile_inventory`
maps observed identities onto root-authored identities and unions their natures.
Unmatched observations remain observed-only. Inspection never rewrites
`poly.yaml`. Removing an authored nature removes only that declaration: the next
inspection can still observe the same nature. This release does not add
per-nature provenance storage or exclusion rules.

Poly selects providers by verb. `propose()` decides applicability using natures,
parameters, relations, and domain context. Manifest nature lists are descriptive,
not an exhaustive core filter. There is no mandatory `supports()` method. Empty
selection/creation and actions covering supporting nodes outside the requested
selection retain their existing semantics.

An empty proposal without rejection means the provider has nothing to contribute
(for example, another tool was requested). A rejected candidate explains why a
relevant candidate cannot be proposed. Git/Maven retain their existing explicit
nature rejections for selected nonmatching nodes. `RejectedCandidate.missing` is
a diagnostic, never an executable prerequisite or a request to find more verbs.
The planner preserves and sorts rejections. Existing reporting groups/bounds
diagnostics; the fixture emits at most one rejection per selected non-Java node.
Accepted actions can remain executable alongside rejected candidates.

## Finite prerequisites: AND requirements, OR producers

- All `requires` facts must be available before an action starts.
- An initial fact is available immediately, even if actions also produce it.
- Any successful producer supplies its facts; every producer remains in the plan.
- Failed actions supply no facts. A successful alternative can still unblock a
  consumer. If all alternatives fail, that consumer becomes blocked.
- Facts are monotonic, scoped to one run, and never inferred from their names.
- Claims detect competing ownership; execution resources control overlap. Neither
  substitutes for causal facts. Alternative producers still need compatible claims.

The audit reproduced false cycle diagnoses for seeded self-dependency, an
externally seeded two-action cycle, and a cycle with an independent alternative
producer. The old graph connected consumers to every producer unconditionally.
The runtime already admitted actions using available facts.

The planner now computes a success-only least fixed point over the **existing**
actions, starting from initial facts. A work queue propagates each newly reachable
fact to waiting consumers. Only requirements outside this closure contribute to
cycle diagnostics. This is a feasibility check, not an execution simulation or
producer election. Missing facts without any initial/planned source and genuine
unseeded cycles remain blocking. The executor, frontier scheduling, failure
handling, and serial/parallel behavior are unchanged.

## Minimal blueprint data

`BlueprintDefinition` implements the existing name/description identity protocol
and adds:

| Field | Contract |
| --- | --- |
| `version` | Explicit opaque version, matched exactly during resolution |
| `parameters` | Named string parameters; required unless a default is supplied; optional finite choices |
| `configuration` | Literal string map interpreted by the consuming driver |
| `bindings` | Configuration key → parameter name, with no expressions/interpolation |
| `resources` | Opaque references declared by the owning plugin; resolution performs no I/O |
| `required_contributions` | Exact loaded contribution identities, not implicit installation instructions |

Duplicate parameters, unknown bindings, colliding literal/bound keys, unknown
input parameters, missing required values, invalid choices, unavailable
contributions/resources, and version mismatch fail before negotiation. Resolution
copies/freezes string maps. A `ResolvedBlueprint.to_dict()` is JSON serializable
and records identity, version, validated parameters, configuration, and references.
It does not generate files or have an execute method.

Legacy name/description-only blueprints remain registerable and discoverable;
resolving one produces an explicit "no declarative definition" error. Resource
presence means declared by the plugin, not that bytes have been inspected: the
driver validates/reads the actual resource during its read-only proposal step.
Required contribution versions follow plugin compatibility/dependencies; this
release adds no separate version-range language.

## Configuration declaration and hydration

The independent [Eclipse fixture](../../examples/eclipse-contract/README.md) now
contributes `add eclipse-configuration`. Its facade validates values against a
versioned schema and translates them to ordinary constructor parameters. A
blueprint can provide reusable initial values. The constructor persists the node
in the root composition; a later hydration plan includes source inspections,
workspace coherence and the fixture projection action. The fixture reads the
consolidated run inventory through the SDK and creates a request document.

The former non-add configuration fixture has been removed. There is no application
switch, implicit prerequisite verb, or dynamically appended execution action.
See [configuration hydration](configuration-hydration.md) for implementation
boundaries and tests. The production Eclipse importer remains pending.
