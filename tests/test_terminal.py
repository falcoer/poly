from __future__ import annotations

import io

import pytest

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


def test_native_progress_tracks_terminal_actions_and_clears_on_completion() -> None:
    output = InteractiveOutput()
    actions = (_action("a"), _action("b"))
    document: ReportDocument = {
        "schema": "poly.report/v1",
        "kind": "run",
        "request": {"verb": "verify", "selected_node_ids": ["node"], "parameters": {}},
        "plan": {"id": "plan", "status": "executable", "planned_actions": []},
        "run": {"actions": []},
    }
    renderer = SerializedRunRenderer(
        output,
        actions,
        capabilities=TerminalCapabilities(True, True, True, 80, True),
    )

    renderer.start(document, "poly verify")
    renderer.handle(RunEvent(1, ActionState.RUNNING, "a"))
    renderer.handle(RunEvent(2, ActionState.SUCCEEDED, "a"))
    renderer.handle(RunEvent(3, ActionState.FAILED, "b"))
    renderer.finish(document, 1)

    value = output.getvalue()
    assert "\x1b]9;4;1;0\x07" in value
    assert "\x1b]9;4;1;50\x07" in value
    assert "\x1b]9;4;2;100\x07" in value
    assert value.endswith("\x1b]9;4;0;0\x07")


def test_inline_progress_is_stable_adaptive_and_removed_before_completion() -> None:
    output = InteractiveOutput()
    actions = (_action("a"), _action("b"))
    document: ReportDocument = {
        "schema": "poly.report/v1",
        "kind": "run",
        "request": {"verb": "verify", "selected_node_ids": ["node"], "parameters": {}},
        "plan": {"id": "plan", "status": "executable", "planned_actions": []},
        "run": {"actions": []},
    }
    renderer = SerializedRunRenderer(
        output,
        actions,
        capabilities=TerminalCapabilities(True, True, True, 48),
    )

    renderer.start(document, "poly verify")
    assert "PLAN      [" in output.getvalue()
    assert "0/2 actions ·   0 %" in output.getvalue()
    renderer.handle(RunEvent(1, ActionState.SUCCEEDED, "a"))
    renderer.handle(RunEvent(2, ActionState.BLOCKED, "b"))

    final_paint = output.getvalue().rsplit("\x1b[J", 1)[-1]
    assert final_paint.count("PLAN WARN [") == 1
    assert "2/2 actions · 100 %" in final_paint
    before_finish = len(output.getvalue())
    renderer.finish(document, 1)
    completion = output.getvalue()[before_finish:]
    assert completion.startswith("\x1b[1A\x1b[J")
    assert "PLAN WARN [" not in completion
    assert "FAILURE  poly verify" in completion


def test_inline_progress_uses_compact_fallback_at_narrow_width() -> None:
    output = InteractiveOutput()
    document: ReportDocument = {
        "schema": "poly.report/v1",
        "kind": "run",
        "plan": {"id": "plan", "status": "executable", "planned_actions": []},
    }
    renderer = SerializedRunRenderer(
        output,
        (_action("a"),),
        capabilities=TerminalCapabilities(True, True, False, 24),
    )

    renderer.start(document, "poly verify")

    assert "        PLAN 0/1 0%" in output.getvalue()
    assert "PLAN      [" not in output.getvalue()


def test_native_progress_is_cleared_on_abort() -> None:
    output = InteractiveOutput()
    renderer = SerializedRunRenderer(
        output,
        (_action("a"),),
        capabilities=TerminalCapabilities(True, True, True, 80, True),
    )
    document: ReportDocument = {
        "schema": "poly.report/v1",
        "kind": "run",
        "plan": {"id": "plan", "status": "executable", "planned_actions": []},
    }

    renderer.start(document, "poly verify")
    renderer.abort()

    assert "\x1b]9;4;0;0\x07\x1b[0m\n" in output.getvalue()


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({"TERM_PROGRAM": "iTerm.app"}, True),
        ({"WT_SESSION": "session"}, True),
        ({"TERM_PROGRAM": "Apple_Terminal"}, False),
        ({"TERM_PROGRAM": "iTerm.app", "CI": "true"}, False),
        ({"TERM_PROGRAM": "iTerm.app", "TMUX": "socket"}, False),
    ],
)
def test_native_progress_capability_detection(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str], expected: bool
) -> None:
    for name in ("CI", "TERM", "TERM_PROGRAM", "TMUX", "WT_SESSION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    capabilities = TerminalCapabilities.detect(InteractiveOutput())

    assert capabilities.native_progress is expected
