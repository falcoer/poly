from __future__ import annotations

import io
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue

import pytest

from poly.model import ActionSpec
from poly.reporting import ReportDocument
from poly.runtime import ActionState, RunEvent
from poly.terminal import (
    NavigationKey,
    RunRenderer,
    SerializedRunRenderer,
    TerminalCapabilities,
    TerminalOutputMode,
    _PosixNavigationInput,
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


class FakeNavigationInput:
    def __init__(self) -> None:
        self.keys: Queue[NavigationKey] = Queue()
        self.started = False
        self.stopped = False

    def start(self) -> bool:
        self.started = True
        return True

    def read(self) -> NavigationKey | None:
        try:
            return self.keys.get_nowait()
        except Empty:
            return None

    def stop(self) -> None:
        self.stopped = True

    def press(self, key: NavigationKey) -> None:
        self.keys.put(key)


def _action(action_id: str) -> ActionSpec:
    return ActionSpec(action_id, "fixture", "verify", "fixture/verify", ("node",))


def _document(
    action_ids: tuple[str, ...] = ("a", "b"),
    selected_node_ids: tuple[str, ...] = ("node",),
) -> ReportDocument:
    return {
        "schema": "poly.report/v1",
        "kind": "run",
        "request": {
            "verb": "verify",
            "selected_node_ids": list(selected_node_ids),
            "parameters": {},
        },
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


def _latest_paint(output: io.StringIO) -> str:
    value = output.getvalue()
    markers = ("\x1b[2J\x1b[H", "\x1b[H")
    position, marker = max((value.rfind(item), item) for item in markers)
    return value[position + len(marker) :]


def _wait_for_paint(output: io.StringIO, expected: str) -> str:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        paint = _latest_paint(output)
        if expected in paint:
            return paint
        time.sleep(0.01)
    pytest.fail(f"live renderer did not paint {expected!r}")


def test_renderer_satisfies_execution_protocol() -> None:
    renderer = SerializedRunRenderer(io.StringIO(), ())

    assert isinstance(renderer, RunRenderer)


@pytest.mark.skipif(os.name == "nt", reason="POSIX pseudo-terminal required")
def test_posix_navigation_reads_keys_without_blocking_and_restores_terminal() -> None:
    import pty

    master_descriptor, slave_descriptor = pty.openpty()
    stream = os.fdopen(slave_descriptor, "r")
    navigation = _PosixNavigationInput(stream)
    try:
        assert navigation.start() is True
        os.write(
            master_descriptor,
            b"\x1b[Dpn\x1b[Cf",
        )

        expected = [
            NavigationKey.PREVIOUS,
            NavigationKey.NEXT,
            NavigationKey.FOLLOW,
        ]
        observed: list[NavigationKey] = []
        deadline = time.monotonic() + 1.0
        while len(observed) < len(expected) and time.monotonic() < deadline:
            key = navigation.read()
            if key is not None:
                observed.append(key)
            else:
                time.sleep(0.01)
        assert observed == expected
    finally:
        navigation.stop()
        stream.close()
        os.close(master_descriptor)

    assert navigation.read() is None
    navigation.stop()
    assert _PosixNavigationInput(io.StringIO()).start() is False


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

    final_paint = _latest_paint(output)
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
    node_ids = tuple(f"node-{index}" for index in range(8))
    document = _document(action_ids, node_ids)
    renderer.start(document, "poly verify")
    initial_paint = _latest_paint(output)
    assert "VERIFYING" not in initial_paint
    assert all(node_id not in initial_paint for node_id in node_ids)
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

    live_paint = _latest_paint(output)
    live_lines = live_paint.splitlines()
    assert "PAGE" in live_lines[-2]
    assert "IN PROGRESS" in live_lines[-1]
    assert "VERIFYING" not in live_paint
    assert all(node_id not in live_paint for node_id in node_ids)
    assert len(live_lines) == 8
    assert live_paint.count("\x1b[K") == 8

    renderer.finish(document, 0)
    history = output.getvalue().split("\x1b[?1049l", 1)[1]
    for action_id in action_ids:
        assert history.count(f"{action_id} (fixture/verify)") == 1
    assert "VERIFYING node-0, node-1" in history
    assert "RUNNING" not in history


def test_live_paging_follows_last_page_until_manual_navigation() -> None:
    output = InteractiveOutput()
    navigation = FakeNavigationInput()
    action_ids = tuple(f"action-{index}" for index in range(8))
    renderer = SerializedRunRenderer(
        output,
        tuple(_action(action_id) for action_id in action_ids),
        capabilities=_live_capabilities(height=8),
        navigation_input=navigation,
    )
    renderer.start(_document(action_ids), "poly verify")
    for index, action_id in enumerate(action_ids, start=1):
        renderer.handle(RunEvent(index, ActionState.SUCCEEDED, action_id, "complete"))

    paint = _latest_paint(output)
    page = re.search(r"PAGE (\d+)/(\d+)", paint)
    assert page is not None
    current, total = (int(value) for value in page.groups())
    assert total > 1
    assert current == total
    assert "FOLLOW" in paint
    assert "P/N PAGE" in paint

    clears_before_navigation = output.getvalue().count("\x1b[2J")
    paints_before_navigation = output.getvalue().count("\x1b[H")
    pressed_at = time.monotonic()
    navigation.press(NavigationKey.PREVIOUS)
    paint = _wait_for_paint(output, f"PAGE {total - 1}/{total}")
    assert time.monotonic() - pressed_at < 0.5
    assert "MANUAL" in paint
    assert output.getvalue().count("\x1b[2J") == clears_before_navigation + 1
    assert output.getvalue().count("\x1b[H") == paints_before_navigation + 1

    renderer.handle(RunEvent(20, ActionState.SUCCEEDED, action_ids[0], "updated"))
    assert f"PAGE {total - 1}/{total}" in _latest_paint(output)
    assert output.getvalue().count("\x1b[2J") == clears_before_navigation + 1

    navigation.press(NavigationKey.NEXT)
    paint = _wait_for_paint(output, f"PAGE {total}/{total}")
    assert "MANUAL" in paint

    navigation.press(NavigationKey.FOLLOW)
    paint = _wait_for_paint(output, "· FOLLOW")
    assert f"PAGE {total}/{total}" in paint
    assert "FOLLOW" in paint

    renderer.finish(_document(action_ids), 0)
    assert navigation.started is True
    assert navigation.stopped is True


def test_live_rows_keep_running_actions_after_deterministic_terminal_rows() -> None:
    output = InteractiveOutput()
    actions = tuple(_action(action_id) for action_id in ("a", "b", "c", "d"))
    renderer = SerializedRunRenderer(output, actions, capabilities=_live_capabilities())
    renderer.start(_document(("a", "b", "c", "d")), "poly verify")

    renderer.handle(RunEvent(1, ActionState.RUNNING, "a"))
    renderer.handle(RunEvent(2, ActionState.SUCCEEDED, "b"))
    renderer.handle(RunEvent(3, ActionState.RUNNING, "c"))
    renderer.handle(RunEvent(4, ActionState.FAILED, "d"))

    assert [action_id for action_id, _ in renderer._ordered_rows()] == ["b", "d", "a", "c"]

    renderer.handle(RunEvent(5, ActionState.SUCCEEDED, "a"))
    assert [action_id for action_id, _ in renderer._ordered_rows()] == ["a", "b", "d", "c"]
    renderer.finish(_document(("a", "b", "c", "d")), 1)


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
