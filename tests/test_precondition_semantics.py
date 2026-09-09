"""The planner and executor share AND requirements / OR producers semantics."""

from pathlib import Path

import pytest

from poly.driver import ExecutionContext
from poly.model import (
    ActionSpec,
    Constraint,
    DriverProposal,
    Inventory,
    Node,
    PlanningRequest,
    PlanStatus,
)
from poly.planning import Planner
from poly.runtime import ActionAttempt, ActionState, Executor


def action(name: str, requires: tuple[str, ...], produces: tuple[str, ...]) -> ActionSpec:
    return ActionSpec(
        name,
        "fixture",
        "verify",
        "fixture/verify",
        ("node",),
        requires=frozenset(Constraint(key) for key in requires),
        produces=frozenset(Constraint(key) for key in produces),
        concurrency_safe=True,
    )


@pytest.mark.parametrize("jobs", [1, 2])
@pytest.mark.parametrize(
    ("actions", "initial", "failures", "expected"),
    [
        ((action("self", ("x",), ("x",)),), ("x",), (), {"self": ActionState.SUCCEEDED}),
        (
            (action("a", ("y",), ("x",)), action("b", ("x",), ("y",))),
            ("x",),
            (),
            {"a": ActionState.SUCCEEDED, "b": ActionState.SUCCEEDED},
        ),
        (
            (action("a", ("y",), ("x",)), action("b", ("x",), ("y",)), action("seed", (), ("x",))),
            (),
            (),
            {"a": ActionState.SUCCEEDED, "b": ActionState.SUCCEEDED, "seed": ActionState.SUCCEEDED},
        ),
        (
            (action("a", (), ("x",)), action("b", (), ("x",)), action("c", ("x",), ())),
            (),
            ("a",),
            {"a": ActionState.FAILED, "b": ActionState.SUCCEEDED, "c": ActionState.SUCCEEDED},
        ),
        (
            (action("a", (), ("x",)), action("b", (), ("x",)), action("c", ("x",), ())),
            (),
            ("a", "b"),
            {"a": ActionState.FAILED, "b": ActionState.FAILED, "c": ActionState.BLOCKED},
        ),
        (
            (action("a", (), ("x",)), action("b", ("x",), ())),
            ("x",),
            ("a",),
            {"a": ActionState.FAILED, "b": ActionState.SUCCEEDED},
        ),
    ],
)
def test_finite_plan_readiness(
    tmp_path: Path,
    jobs: int,
    actions: tuple[ActionSpec, ...],
    initial: tuple[str, ...],
    failures: tuple[str, ...],
    expected: dict[str, ActionState],
) -> None:
    request = PlanningRequest(
        "verify",
        Inventory((Node("node", "node"),)),
        ("node",),
        initial_constraints=frozenset(Constraint(key) for key in initial),
    )
    plan = Planner(()).negotiate_proposals(request, (DriverProposal("fixture", actions),))
    assert plan.status is PlanStatus.EXECUTABLE

    class Runner:
        def run(self, spec: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            return ActionAttempt(spec.id not in failures, spec.id)

    result = Executor(Runner(), jobs=jobs).execute(
        plan,
        ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / plan.id),
    )
    assert {item.action_id: item.state for item in result.actions} == expected


@pytest.mark.parametrize(
    ("actions", "codes"),
    [
        ((action("self", ("x",), ("x",)),), {"constraint.cycle"}),
        ((action("a", ("y",), ("x",)), action("b", ("x",), ("y",))), {"constraint.cycle"}),
        ((action("a", ("missing",), ("x",)), action("b", ("x",), ())), {"constraint.missing"}),
        ((action("a", (), ("x",)), action("b", ("x", "missing"), ())), {"constraint.missing"}),
    ],
)
def test_unreachable_facts_are_diagnosed(actions: tuple[ActionSpec, ...], codes: set[str]) -> None:
    request = PlanningRequest("verify", Inventory((Node("node", "node"),)), ("node",))
    plan = Planner(()).negotiate_proposals(request, (DriverProposal("fixture", actions),))
    assert plan.status is PlanStatus.BLOCKED
    assert {item.code for item in plan.diagnostics} == codes
