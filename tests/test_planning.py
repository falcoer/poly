from __future__ import annotations

from dataclasses import dataclass

from poly.model import (
    ActionClaim,
    ActionSpec,
    Constraint,
    DriverProposal,
    Inventory,
    Node,
    PlanningRequest,
    PlanStatus,
    RejectedCandidate,
)
from poly.planning import Planner


@dataclass(frozen=True)
class StubProvider:
    name: str
    verbs: frozenset[str]
    proposal: DriverProposal
    calls: list[str]

    def propose(self, request: PlanningRequest) -> DriverProposal:
        self.calls.append(request.verb)
        return self.proposal


def request(
    verb: str = "verify", *, initial: frozenset[Constraint] = frozenset()
) -> PlanningRequest:
    inventory = Inventory((Node("service", "service", ("maven/module",)),))
    return PlanningRequest(verb, inventory, ("service",), initial_constraints=initial)


def action(
    action_id: str,
    *,
    driver: str = "example",
    verb: str = "verify",
    requires: frozenset[Constraint] = frozenset(),
    produces: frozenset[Constraint] = frozenset(),
    claim: ActionClaim | None = None,
) -> ActionSpec:
    return ActionSpec(
        id=action_id,
        driver=driver,
        verb=verb,
        operation="project/verify",
        node_ids=("service",),
        requires=requires,
        produces=produces,
        claims=frozenset((claim,)) if claim else frozenset(),
    )


def test_planner_queries_only_requested_verb_and_keeps_rejections() -> None:
    verify_calls: list[str] = []
    publish_calls: list[str] = []
    accepted = action("verify:service")
    providers = (
        StubProvider(
            "verify-driver",
            frozenset(("verify",)),
            DriverProposal("verify", (accepted,)),
            verify_calls,
        ),
        StubProvider(
            "publish-driver",
            frozenset(("publish",)),
            DriverProposal(
                "publish",
                rejected=(RejectedCandidate("publish", "publish", "artifact absent"),),
            ),
            publish_calls,
        ),
    )

    plan = Planner(providers).negotiate(request())

    assert plan.status is PlanStatus.EXECUTABLE
    assert plan.actions == (accepted,)
    assert verify_calls == ["verify"]
    assert publish_calls == []


def test_missing_constraint_blocks_without_extending_plan() -> None:
    missing = Constraint("artifact/service/available")
    proposed = action("publish:service", verb="publish", requires=frozenset((missing,)))
    provider = StubProvider(
        "publisher", frozenset(("publish",)), DriverProposal("publisher", (proposed,)), []
    )

    plan = Planner((provider,)).negotiate(request("publish"))

    assert plan.status is PlanStatus.BLOCKED
    assert [item.code for item in plan.diagnostics] == ["constraint.missing"]
    assert plan.actions == (proposed,)


def test_initial_and_planned_constraints_make_plan_executable() -> None:
    credentials = Constraint("credentials/nexus/validated")
    built = Constraint("artifact/service/verified")
    first = action("a-verify", requires=frozenset((credentials,)), produces=frozenset((built,)))
    second = action("b-report", requires=frozenset((built,)))
    provider = StubProvider(
        "provider", frozenset(("verify",)), DriverProposal("provider", (second, first)), []
    )

    plan = Planner((provider,)).negotiate(request(initial=frozenset((credentials,))))

    assert plan.status is PlanStatus.EXECUTABLE
    assert [item.id for item in plan.actions] == ["a-verify", "b-report"]
    assert plan.ready_action_ids == ("a-verify",)


def test_competing_claims_are_conflicts_independent_of_provider_order() -> None:
    claim = ActionClaim("container-build", "node:service")
    dockerfile = action("dockerfile", driver="dockerfile", claim=claim)
    jkube = action("jkube", driver="jkube", claim=claim)
    left = StubProvider("z-jkube", frozenset(("verify",)), DriverProposal("jkube", (jkube,)), [])
    right = StubProvider(
        "a-dockerfile", frozenset(("verify",)), DriverProposal("dockerfile", (dockerfile,)), []
    )

    plan = Planner((left, right)).negotiate(request())
    reversed_plan = Planner((right, left)).negotiate(request())

    assert plan.status is PlanStatus.CONFLICT
    assert [item.code for item in plan.diagnostics] == ["claim.conflict"]
    assert plan.id == reversed_plan.id
    assert plan.actions == reversed_plan.actions


def test_wrong_verb_unselected_nodes_duplicate_ids_and_cycles_are_diagnosed() -> None:
    first_done = Constraint("first/done")
    second_done = Constraint("second/done")
    wrong = ActionSpec(
        id="duplicate",
        driver="bad",
        verb="publish",
        operation="bad",
        node_ids=("other",),
        requires=frozenset((second_done,)),
        produces=frozenset((first_done,)),
    )
    duplicate = action(
        "duplicate", requires=frozenset((first_done,)), produces=frozenset((second_done,))
    )
    provider = StubProvider(
        "bad", frozenset(("verify",)), DriverProposal("bad", (wrong, duplicate)), []
    )

    plan = Planner((provider,)).negotiate(request())

    assert plan.status is PlanStatus.CONFLICT
    assert {item.code for item in plan.diagnostics} == {
        "action.duplicate-id",
        "action.outside-selection",
        "action.wrong-verb",
        "constraint.cycle",
    }


def test_empty_plan_is_a_normal_result() -> None:
    rejected = RejectedCandidate("maven", "publish", "no artifact", ("service",))
    provider = StubProvider(
        "maven", frozenset(("publish",)), DriverProposal("maven", rejected=(rejected,)), []
    )

    plan = Planner((provider,)).negotiate(request("publish"))

    assert plan.status is PlanStatus.EMPTY
    assert plan.rejected == (rejected,)
    assert plan.actions == ()
