from __future__ import annotations

import io
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from poly.model import ActionSpec
from poly.reporting import ReportDocument
from poly.runtime import ActionState, RunEvent
from poly.terminal import (
    RunRenderer,
    SerializedRunRenderer,
    TerminalCapabilities,
    TerminalOutputMode,
)


class InteractiveOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


class ThreadRecordingOutput(InteractiveOutput):
    def __init__(self) -> None:
        super().__init__()
        self.writer_threads: list[str] = []

    def write(self, value: str) -> int:
        self.writer_threads.append(threading.current_thread().name)
        return super().write(value)


class BrokenOutput(InteractiveOutput):
    def write(self, value: str) -> int:
        raise OSError("terminal unavailable")


class AlternateScreenFailureOutput(InteractiveOutput):
    def write(self, value: str) -> int:
        if value == "\x1b[?1049h":
            raise OSError("alternate screen unavailable")
        return super().write(value)


def _action(action_id: str) -> ActionSpec:
    return ActionSpec(action_id, "fixture", "verify", "fixture/verify", ("node",))


def _document(action_ids: tuple[str, ...] = ("a", "b")) -> ReportDocument:
    return {
        "schema": "poly.report/v1",
        "kind": "run",
        "request": {"verb": "verify", "selected_node_ids": ["node"], "parameters": {}},
        "plan": {
            "id": "plan",
            "status": "executable",
            "planned_actions": [
                {"id": action_id, "operation": "fixture/verify"} for action_id in action_ids
            ],
            "diagnostics": [],
        },
        "run": {
            "actions": [
                {
                    "action_id": action_id,
                    "state": "succeeded",
                    "blocked_by": [],
                    "completed_at": "2026-09-04T12:00:00.000Z",
                    "attempt": {"summary": f"{action_id} complete"},
                }
                for action_id in action_ids
            ]
        },
    }


def _live_capabilities(
    *, width: int = 100, height: int = 24, native_progress: bool = False
) -> TerminalCapabilities:
    return TerminalCapabilities(True, True, True, width, native_progress, height, True)


def test_renderer_satisfies_execution_protocol() -> None:
    renderer = SerializedRunRenderer(io.StringIO(), ())

    assert isinstance(renderer, RunRenderer)


def test_renderer_rejects_a_second_start() -> None:
    renderer = SerializedRunRenderer(
        io.StringIO(),
        (_action("a"),),
        capabilities=TerminalCapabilities(False, False, False, 72),
    )
    renderer.start(_document(("a",)), "poly verify")

    with pytest.raises(RuntimeError, match="already started"):
        renderer.start(_document(("a",)), "poly verify")

    renderer.abort()


def test_live_renderer_replaces_interleaved_rows_in_plan_order() -> None:
    output = InteractiveOutput()
    actions = (_action("a"), _action("b"))
    renderer = SerializedRunRenderer(output, actions, capabilities=_live_capabilities())
    renderer.start(_document(), "poly verify")

    renderer.handle(RunEvent(1, ActionState.RUNNING, "b"))
    renderer.handle(RunEvent(2, ActionState.RUNNING, "a"))
    renderer.handle(
        RunEvent(
            3,
            ActionState.SUCCEEDED,
            "b",
            "b complete",
            "2026-09-04T12:00:01.000Z",
        )
    )
    renderer.handle(
        RunEvent(
            4,
            ActionState.SUCCEEDED,
            "a",
            "a complete",
            "2026-09-04T12:00:02.000Z",
        )
    )

    final_paint = output.getvalue().rsplit("\x1b[2J\x1b[H", 1)[-1]
    assert final_paint.count(" a (fixture/verify)") == 1
    assert final_paint.count(" b (fixture/verify)") == 1
    assert final_paint.index(" a (fixture/verify)") < final_paint.index(" b (fixture/verify)")
    assert "RUNNING" not in final_paint
    renderer.finish(_document(), 0)


def test_flow_renderer_emits_only_terminal_rows_without_cursor_controls() -> None:
    output = io.StringIO()
    renderer = SerializedRunRenderer(
        output,
        (_action("a"),),
        capabilities=TerminalCapabilities(False, False, False, 72),
    )
    renderer.start(_document(("a",)), "poly verify")

    renderer.handle(RunEvent(1, ActionState.RUNNING, "a"))
    renderer.handle(
        RunEvent(
            2,
            ActionState.SUCCEEDED,
            "a",
            "complete",
            "2026-09-04T12:00:00.000Z",
        )
    )
    renderer.finish(_document(("a",)), 0)

    value = output.getvalue()
    assert renderer.mode is TerminalOutputMode.FLOW
    assert "RUNNING" not in value
    assert value.count("✓ OK") == 1
    assert "\x1b[" not in value
    assert "\x1b]" not in value


def test_force_flow_disables_live_on_capable_terminal() -> None:
    output = InteractiveOutput()
    renderer = SerializedRunRenderer(
        output,
        (_action("a"),),
        capabilities=_live_capabilities(),
        force_flow=True,
    )

    renderer.start(_document(("a",)), "poly verify --flow")
    renderer.finish(_document(("a",)), 0)

    assert renderer.mode is TerminalOutputMode.FLOW
    assert "\x1b[?1049h" not in output.getvalue()


def test_live_start_failure_restores_terminal_and_falls_back_to_flow() -> None:
    output = AlternateScreenFailureOutput()
    renderer = SerializedRunRenderer(
        output,
        (_action("a"),),
        capabilities=_live_capabilities(),
    )

    renderer.start(_document(("a",)), "poly verify")
    renderer.handle(RunEvent(1, ActionState.SUCCEEDED, "a"))
    renderer.finish(_document(("a",)), 0)

    assert renderer.mode is TerminalOutputMode.FLOW
    assert output.getvalue().startswith("\x1b[0m\x1b[?1049l")
    assert output.getvalue().count("a (fixture/verify)") == 1


def test_live_renderer_restores_terminal_and_abort_is_idempotent() -> None:
    output = InteractiveOutput()
    renderer = SerializedRunRenderer(
        output,
        (_action("a"),),
        capabilities=_live_capabilities(),
    )
    renderer.start(_document(("a",)), "poly verify")

    renderer.abort()
    renderer.abort()

    value = output.getvalue()
    assert value.count("\x1b[?1049h") == 1
    assert value.count("\x1b[?1049l") == 1
    assert "· PENDING  a (fixture/verify)" in value
    assert "✗ ABORTED  poly verify" in value


def test_aborted_live_history_retains_latest_action_state_once() -> None:
    output = InteractiveOutput()
    renderer = SerializedRunRenderer(
        output,
        (_action("a"), _action("b")),
        capabilities=_live_capabilities(),
    )
    renderer.start(_document(), "poly verify")
    renderer.handle(RunEvent(1, ActionState.RUNNING, "a"))

    renderer.abort()

    history = output.getvalue().split("\x1b[?1049l", 1)[1]
    assert history.count("a (fixture/verify)") == 1
    assert "· PENDING  b (fixture/verify)" in history


def test_flow_abort_is_append_only() -> None:
    output = io.StringIO()
    renderer = SerializedRunRenderer(
        output,
        (_action("a"),),
        capabilities=TerminalCapabilities(False, False, False, 72),
    )
    renderer.start(_document(("a",)), "poly verify --flow")

    renderer.abort()

    assert "✗ ABORTED  poly verify --flow" in output.getvalue()
    assert "\x1b[?1049" not in output.getvalue()


def test_renderer_owns_start_completion_and_ignores_non_visual_events() -> None:
    output = io.StringIO()
    renderer = SerializedRunRenderer(
        output,
        (_action("a"),),
        capabilities=TerminalCapabilities(False, False, False, 64),
    )
    renderer.start(_document(("a",)), "poly verify")
    renderer.handle(RunEvent(1, ActionState.PLANNED, "a"))
    renderer.finish(_document(("a",)), 0)
    renderer.handle(RunEvent(2, ActionState.SUCCEEDED, "a"))

    value = output.getvalue()
    assert "VERIFYING node" in value
    assert "SUCCESS  poly verify" in value
    assert value.count("a (fixture/verify)") == 0


def test_native_progress_tracks_terminal_actions_and_clears_on_completion() -> None:
    output = InteractiveOutput()
    actions = (_action("a"), _action("b"))
    renderer = SerializedRunRenderer(
        output,
        actions,
        capabilities=_live_capabilities(native_progress=True),
    )
    renderer.start(_document(), "poly verify")
    renderer.handle(RunEvent(1, ActionState.RUNNING, "a"))
    renderer.handle(RunEvent(2, ActionState.SUCCEEDED, "a"))
    renderer.handle(RunEvent(3, ActionState.FAILED, "b"))
    renderer.finish(_document(), 1)

    value = output.getvalue()
    assert "\x1b]9;4;1;0\x07" in value
    assert "\x1b]9;4;1;50\x07" in value
    assert "\x1b]9;4;2;100\x07" in value
    assert value.endswith("\x1b]9;4;0;0\x07")


def test_live_renderer_pages_inside_viewport_and_emits_one_final_history() -> None:
    output = InteractiveOutput()
    action_ids = tuple(f"action-{index}" for index in range(8))
    actions = tuple(_action(action_id) for action_id in action_ids)
    renderer = SerializedRunRenderer(
        output,
        actions,
        capabilities=_live_capabilities(height=8),
    )
    document = _document(action_ids)
    renderer.start(document, "poly verify")
    for index, action_id in enumerate(action_ids, start=1):
        renderer.handle(
            RunEvent(
                index,
                ActionState.SUCCEEDED,
                action_id,
                "complete",
                f"2026-09-04T12:00:{index:02d}.000Z",
            )
        )

    live_paint = output.getvalue().rsplit("\x1b[2J\x1b[H", 1)[-1]
    assert "PAGE" in live_paint
    assert len(live_paint.splitlines()) <= 8

    renderer.finish(document, 0)
    history = output.getvalue().split("\x1b[?1049l", 1)[1]
    for action_id in action_ids:
        assert history.count(f"{action_id} (fixture/verify)") == 1
    assert "RUNNING" not in history


def test_live_progress_contains_elapsed_time_and_bracketed_timestamp() -> None:
    output = InteractiveOutput()
    renderer = SerializedRunRenderer(
        output,
        (_action("a"),),
        capabilities=_live_capabilities(),
    )

    renderer.start(_document(("a",)), "poly verify")
    renderer.abort()

    live = output.getvalue().split("\x1b[?1049l", 1)[0]
    assert "IN PROGRESS" in live
    assert "00:00:00" in live
    assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]", live)


def test_small_terminal_automatically_falls_back_to_flow() -> None:
    output = InteractiveOutput()
    renderer = SerializedRunRenderer(
        output,
        (_action("a"),),
        capabilities=TerminalCapabilities(True, True, True, 48, False, 7, True),
    )

    renderer.start(_document(("a",)), "poly verify")
    renderer.finish(_document(("a",)), 0)

    assert renderer.mode is TerminalOutputMode.FLOW
    assert "\x1b[?1049h" not in output.getvalue()


@pytest.mark.parametrize(("verbosity", "action_ids"), [(-1, ("a",)), (0, ())])
def test_live_is_not_started_when_there_is_nothing_to_display(
    verbosity: int,
    action_ids: tuple[str, ...],
) -> None:
    output = InteractiveOutput()
    renderer = SerializedRunRenderer(
        output,
        tuple(_action(action_id) for action_id in action_ids),
        verbosity=verbosity,
        capabilities=_live_capabilities(),
    )

    renderer.start(_document(action_ids), "poly verify")
    renderer.finish(_document(action_ids), 0)

    assert renderer.mode is TerminalOutputMode.FLOW
    assert "\x1b[?1049h" not in output.getvalue()


def test_concurrent_event_producers_leave_one_complete_history() -> None:
    output = ThreadRecordingOutput()
    action_ids = tuple(f"action-{index}" for index in range(12))
    renderer = SerializedRunRenderer(
        output,
        tuple(_action(action_id) for action_id in action_ids),
        capabilities=_live_capabilities(height=8),
    )
    document = _document(action_ids)
    renderer.start(document, "poly verify")

    def complete(index_and_id: tuple[int, str]) -> None:
        index, action_id = index_and_id
        renderer.handle(RunEvent(index * 2, ActionState.RUNNING, action_id))
        renderer.handle(
            RunEvent(
                index * 2 + 1,
                ActionState.SUCCEEDED,
                action_id,
                "complete",
                f"2026-09-04T12:00:{index:02d}.000Z",
            )
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(complete, enumerate(action_ids)))

    renderer.finish(document, 0)

    history = output.getvalue().split("\x1b[?1049l", 1)[1]
    assert all(history.count(f"{action_id} (fixture/verify)") == 1 for action_id in action_ids)
    assert set(output.writer_threads) == {"poly-terminal"}


def test_all_terminal_writes_are_owned_by_dispatcher_thread() -> None:
    output = ThreadRecordingOutput()
    renderer = SerializedRunRenderer(
        output,
        (_action("a"),),
        capabilities=_live_capabilities(),
    )

    renderer.start(_document(("a",)), "poly verify")
    renderer.handle(RunEvent(1, ActionState.SUCCEEDED, "a"))
    renderer.finish(_document(("a",)), 0)

    assert output.writer_threads
    assert set(output.writer_threads) == {"poly-terminal"}


def test_dispatcher_failure_is_reported_and_attempts_terminal_restoration() -> None:
    renderer = SerializedRunRenderer(
        BrokenOutput(),
        (_action("a"),),
        capabilities=_live_capabilities(native_progress=True),
    )

    with pytest.raises(RuntimeError, match="terminal rendering failed"):
        renderer.start(_document(("a",)), "poly verify")


@pytest.mark.parametrize(
    ("environment", "expected_native"),
    [
        ({"TERM_PROGRAM": "iTerm.app"}, True),
        ({"WT_SESSION": "session"}, True),
        ({"TERM_PROGRAM": "Apple_Terminal"}, False),
        ({"TERM_PROGRAM": "iTerm.app", "CI": "true"}, False),
        ({"TERM_PROGRAM": "iTerm.app", "TMUX": "socket"}, False),
    ],
)
def test_terminal_capability_detection(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    expected_native: bool,
) -> None:
    for name in ("CI", "TERM", "TERM_PROGRAM", "TMUX", "WT_SESSION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        "poly.terminal.shutil.get_terminal_size",
        lambda fallback: os.terminal_size((100, 30)),
    )

    capabilities = TerminalCapabilities.detect(InteractiveOutput())

    assert capabilities.native_progress is expected_native
    assert capabilities.width == 100
    assert capabilities.height == 30
    assert capabilities.supports_live is ("CI" not in environment)


def test_terminal_capability_detection_requires_a_known_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("CI", "TERM", "TERM_PROGRAM", "TMUX", "WT_SESSION"):
        monkeypatch.delenv(name, raising=False)

    capabilities = TerminalCapabilities.detect(InteractiveOutput())

    assert capabilities.interactive is True
    assert capabilities.cursor_updates is False
    assert capabilities.alternate_screen is False
    assert capabilities.supports_live is False
