from __future__ import annotations

import io

from poly.model import ActionSpec
from poly.reporting import ReportDocument
from poly.runtime import ActionState, RunEvent
from poly.terminal import SerializedRunRenderer, TerminalCapabilities


class InteractiveOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


def _action(action_id: str) -> ActionSpec:
    return ActionSpec(action_id, "fixture", "verify", "fixture/verify", ("node",))


def test_interactive_renderer_replaces_interleaved_rows_in_plan_order() -> None:
    output = InteractiveOutput()
    actions = (_action("a"), _action("b"))
    renderer = SerializedRunRenderer(
        output,
        actions,
        capabilities=TerminalCapabilities(True, True, True, 80),
    )

    renderer.handle(RunEvent(1, ActionState.RUNNING, "b"))
    renderer.handle(RunEvent(2, ActionState.RUNNING, "a"))
    renderer.handle(RunEvent(3, ActionState.SUCCEEDED, "b", "b complete"))
    renderer.handle(RunEvent(4, ActionState.SUCCEEDED, "a", "a complete"))

    final_paint = output.getvalue().rsplit("\x1b[J", 1)[-1]
    assert final_paint.count(" a (fixture/verify)") == 1
    assert final_paint.count(" b (fixture/verify)") == 1
    assert final_paint.index(" a (fixture/verify)") < final_paint.index(" b (fixture/verify)")
    assert "RUNNING" not in final_paint


def test_append_only_renderer_emits_only_terminal_rows_without_controls() -> None:
    output = io.StringIO()
    action = _action("a")
    renderer = SerializedRunRenderer(
        output,
        (action,),
        capabilities=TerminalCapabilities(False, False, False, 72),
    )

    renderer.handle(RunEvent(1, ActionState.RUNNING, "a"))
    renderer.handle(RunEvent(2, ActionState.SUCCEEDED, "a", "complete"))

    value = output.getvalue()
    assert "RUNNING" not in value
    assert value.count("✓ OK") == 1
    assert "\x1b[" not in value
    assert "\x1b]" not in value


def test_interactive_abort_resets_terminal_and_is_idempotent() -> None:
    output = InteractiveOutput()
    renderer = SerializedRunRenderer(
        output,
        (),
        capabilities=TerminalCapabilities(True, True, False, 72),
    )

    renderer.abort()
    renderer.abort()

    assert output.getvalue() == "\x1b[0m\n"


def test_renderer_owns_start_completion_and_ignores_non_visual_events() -> None:
    output = InteractiveOutput()
    action = _action("a")
    document: ReportDocument = {
        "schema": "poly.report/v1",
        "kind": "run",
        "request": {"verb": "verify", "selected_node_ids": ["node"], "parameters": {}},
        "plan": {
            "id": "plan",
            "status": "executable",
            "planned_actions": [],
            "diagnostics": [],
        },
        "run": {"actions": []},
    }
    renderer = SerializedRunRenderer(
        output,
        (action,),
        capabilities=TerminalCapabilities(True, True, False, 64),
    )

    renderer.start(document, "poly verify")
    renderer.handle(RunEvent(1, ActionState.PLANNED, "a"))
    renderer.finish(document, 0)
    renderer.handle(RunEvent(2, ActionState.SUCCEEDED, "a"))

    value = output.getvalue()
    assert "VERIFYING node" in value
    assert "SUCCESS  poly verify" in value
    assert value.count("a (fixture/verify)") == 0
