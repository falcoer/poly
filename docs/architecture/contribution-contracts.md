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

The containing Extension API is now **1.1**, an additive minor revision; plugins
requiring 1.0 remain accepted. Plugins using blueprint definitions should request
1.1. Driver API remains **1.1**. Python contexts expose model objects and paths;
this is neither a security sandbox nor an IPC protocol.

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

## Facade and core resolution sequence

The existing string map suffices for the independent
[Eclipse fixture](../../examples/eclipse-contract/README.md):

1. Core resolves `facade(configure, eclipse-fixture)` from the registry.
2. `translate(FacadeRequest)` normalizes `project_name` without effects.
3. Core calls `resolve_blueprint("eclipse-java", values, version="1.0.0")`.
4. Core constructs one `PlanningRequest` for the facade's verb, inventory,
   selection, and the resolved configuration map; the driver proposes actions.
5. Core validates/freezes that finite plan and executes its serialized actions.

The fixture driver freezes the generated XML in a process command before execution.
No blueprint or facade calls the planner, executor, renderer, or another driver.
This proves a non-add facade without changing `CommandFacade.translate` or adding
a structured intent type. The registry/SDK sequence is implemented and tested;
automatic CLI facade binding still targets **add only**. A generic configure CLI,
production Eclipse driver, managed output lifecycle, stale-plan protection, and
persisted blueprint selection in workspace manifests belong to later milestones.
No speculative command syntax is advertised here.

## Compatibility and evidence

Manifest/lock schemas, prepared journals, plan/report envelopes, action fields,
legacy driver registration, and CLI add translation are unchanged. Prepared
journals still resolve once before execution; existing frozen plans keep their
recorded status and are not retroactively repaired. Newly negotiated seeded plans
can now be executable, with a correspondingly different diagnostic fingerprint.
Blueprint definitions add no mandatory workspace field. `.poly/` stays disposable.

Focused evidence: `test_precondition_semantics.py` exercises planner → runtime
with one/two workers; `test_blueprint_contract.py` loads the external plugin and
creates/validates XML through a process action; `test_workspace.py` checks observed
nature retention without authored-file writes. Existing Git/Maven applicability,
serialization, prepared workflows, conformance, and cold/warm benchmarks are
reused. Release evidence and remaining acceptance gates live in
[0.13.1](../releases/0.13.1.md).
