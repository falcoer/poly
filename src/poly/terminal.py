"""Serialized terminal ownership for streamed Poly runs."""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Protocol, TextIO, cast, runtime_checkable

from poly.model import ActionSpec
from poly.reporting import (
    ReportDocument,
    render_cli,
    render_cli_completion,
    render_cli_event,
    render_cli_progress,
    render_cli_start,
)
from poly.runtime import ActionState, RunEvent

_ENTER_ALTERNATE_SCREEN = "\x1b[?1049h"
_LEAVE_ALTERNATE_SCREEN = "\x1b[?1049l"
_CLEAR_SCREEN = "\x1b[2J\x1b[H"
_HOME_CURSOR = "\x1b[H"
_CLEAR_LINE_TO_END = "\x1b[K"
_CLEAR_TO_END = "\x1b[J"
_RESET_STYLE = "\x1b[0m"
_MINIMUM_LIVE_WIDTH = 64
_MINIMUM_LIVE_HEIGHT = 8


class TerminalOutputMode(StrEnum):
    """Human-readable terminal presentation selected for one execution."""

    LIVE = "live"
    FLOW = "flow"


class NavigationKey(StrEnum):
    """Page navigation commands understood by the live renderer."""

    PREVIOUS = "previous"
    NEXT = "next"
    FOLLOW = "follow"


class NavigationInput(Protocol):
    """Non-blocking terminal input used while the alternate screen is active."""

    def start(self) -> bool: ...

    def read(self) -> NavigationKey | None: ...

    def stop(self) -> None: ...


class _Msvcrt(Protocol):
    def kbhit(self) -> bool: ...

    def getwch(self) -> str: ...


type _TerminalAttributes = list[int | list[bytes | int]]


@dataclass(slots=True)
class _PosixNavigationInput:
    stream: TextIO
    _file_descriptor: int | None = field(default=None, init=False)
    _saved_attributes: _TerminalAttributes | None = field(default=None, init=False)
    _buffer: str = field(default="", init=False)

    def start(self) -> bool:
        if not self.stream.isatty():
            return False
        try:
            import termios
            import tty

            file_descriptor = self.stream.fileno()
            attributes = cast(_TerminalAttributes, termios.tcgetattr(file_descriptor))
            tty.setcbreak(file_descriptor)
        except (AttributeError, OSError, ValueError, termios.error):
            return False
        self._file_descriptor = file_descriptor
        self._saved_attributes = attributes
        return True

    def read(self) -> NavigationKey | None:
        if self._file_descriptor is None:
            return None
        import select

        readable, _, _ = select.select((self._file_descriptor,), (), (), 0)
        if readable:
            self._buffer += os.read(self._file_descriptor, 16).decode(errors="ignore")
        return self._consume_key()

    def stop(self) -> None:
        if self._file_descriptor is None or self._saved_attributes is None:
            return
        import termios

        termios.tcsetattr(
            self._file_descriptor,
            termios.TCSADRAIN,
            self._saved_attributes,
        )
        self._file_descriptor = None
        self._saved_attributes = None
        self._buffer = ""

    def _consume_key(self) -> NavigationKey | None:
        candidates: list[tuple[int, NavigationKey]] = []
        for character, key in {
            "p": NavigationKey.PREVIOUS,
            "n": NavigationKey.NEXT,
            "f": NavigationKey.FOLLOW,
        }.items():
            position = self._buffer.find(character)
            if position >= 0:
                candidates.append((position, key))
        if candidates:
            position, key = min(candidates, key=lambda candidate: candidate[0])
            self._buffer = self._buffer[position + 1 :]
            return key
        self._buffer = ""
        return None


@dataclass(slots=True)
class _WindowsNavigationInput:  # pragma: no cover - exercised on Windows
    stream: TextIO
    _active: bool = field(default=False, init=False)

    def start(self) -> bool:
        self._active = self.stream.isatty()
        return self._active

    def read(self) -> NavigationKey | None:
        if not self._active:
            return None
        msvcrt = cast(_Msvcrt, importlib.import_module("msvcrt"))

        if not msvcrt.kbhit():
            return None
        character = msvcrt.getwch()
        if character in {"\x00", "\xe0"} and msvcrt.kbhit():
            msvcrt.getwch()
            return None
        return {
            "p": NavigationKey.PREVIOUS,
            "n": NavigationKey.NEXT,
            "f": NavigationKey.FOLLOW,
        }.get(character)

    def stop(self) -> None:
        self._active = False


def _navigation_input(stream: TextIO) -> NavigationInput:
    if os.name == "nt":  # pragma: no cover - exercised on Windows
        return _WindowsNavigationInput(stream)
    return _PosixNavigationInput(stream)


@runtime_checkable
class RunRenderer(Protocol):
    """Execution-facing rendering contract independent of terminal strategy."""

    def start(self, document: ReportDocument, command: str) -> None: ...

    def handle(self, event: RunEvent) -> None: ...

    def finish(self, document: ReportDocument, exit_code: int) -> None: ...

    def abort(self) -> None: ...


@dataclass(frozen=True, slots=True)
class TerminalCapabilities:
    interactive: bool
    cursor_updates: bool
    hyperlinks: bool
    width: int
    native_progress: bool = False
    height: int = 24
    alternate_screen: bool = False

    @classmethod
    def detect(cls, stream: TextIO) -> TerminalCapabilities:
        interactive = stream.isatty()
        term = os.environ.get("TERM", "")
        continuous_integration = "CI" in os.environ
        known_terminal = bool(term) and term.lower() != "dumb"
        windows_terminal = bool(os.environ.get("WT_SESSION"))
        cursor_updates = (
            interactive and not continuous_integration and (known_terminal or windows_terminal)
        )
        hyperlinks = cursor_updates
        terminal_program = os.environ.get("TERM_PROGRAM", "").lower()
        native_progress = (
            cursor_updates
            and "TMUX" not in os.environ
            and (terminal_program == "iterm.app" or windows_terminal)
        )
        size = shutil.get_terminal_size(fallback=(72, 24))
        alternate_screen = cursor_updates and (known_terminal or windows_terminal)
        return cls(
            interactive,
            cursor_updates,
            hyperlinks,
            size.columns,
            native_progress,
            size.lines,
            alternate_screen,
        )

    @property
    def supports_live(self) -> bool:
        return (
            self.interactive
            and self.cursor_updates
            and self.alternate_screen
            and self.width >= _MINIMUM_LIVE_WIDTH
            and self.height >= _MINIMUM_LIVE_HEIGHT
        )


@dataclass(frozen=True, slots=True)
class _EventCommand:
    event: RunEvent
    completed: Event


@dataclass(frozen=True, slots=True)
class _FinishCommand:
    document: ReportDocument
    exit_code: int
    completed: Event


@dataclass(frozen=True, slots=True)
class _AbortCommand:
    completed: Event


@dataclass(frozen=True, slots=True)
class _NavigationCommand:
    key: NavigationKey | None


type _RenderCommand = _EventCommand | _FinishCommand | _AbortCommand | _NavigationCommand


@dataclass(slots=True)
class SerializedRunRenderer:
    """Own all terminal writes through one serialized dispatcher."""

    stream: TextIO
    actions: tuple[ActionSpec, ...]
    verbosity: int = 0
    color: bool = False
    capabilities: TerminalCapabilities | None = None
    force_flow: bool = False
    input_stream: TextIO | None = None
    navigation_input: NavigationInput | None = None
    _rows: dict[str, str] = field(default_factory=dict, init=False)
    _states: dict[str, ActionState] = field(default_factory=dict, init=False)
    _completed_action_ids: set[str] = field(default_factory=set, init=False)
    _failed: bool = field(default=False, init=False)
    _blocked: bool = field(default=False, init=False)
    _progress_active: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)
    _accepting: bool = field(default=False, init=False)
    _mode: TerminalOutputMode | None = field(default=None, init=False)
    _command: str = field(default="", init=False)
    _start_document: ReportDocument | None = field(default=None, init=False)
    _start_lines: tuple[str, ...] = field(default=(), init=False)
    _live_start_lines: tuple[str, ...] = field(default=(), init=False)
    _compact_live: bool = field(default=False, init=False)
    _live_painted: bool = field(default=False, init=False)
    _painted_layout: tuple[int, int, bool] | None = field(default=None, init=False)
    _current_page: int = field(default=0, init=False)
    _follow_last_page: bool = field(default=True, init=False)
    _live_pages: tuple[tuple[str, ...], ...] = field(default=((),), init=False)
    _navigation_active: bool = field(default=False, init=False)
    _navigation_stop: Event = field(default_factory=Event, init=False)
    _navigation_thread: Thread | None = field(default=None, init=False)
    _elapsed_started: float | None = field(default=None, init=False)
    _next_refresh_at: float | None = field(default=None, init=False)
    _commands: Queue[_RenderCommand] = field(default_factory=Queue, init=False)
    _submission_lock: Lock = field(default_factory=Lock, init=False)
    _dispatcher_ready: Event = field(default_factory=Event, init=False)
    _dispatcher_thread: Thread | None = field(default=None, init=False)
    _dispatcher_error: BaseException | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.capabilities is None:
            self.capabilities = TerminalCapabilities.detect(self.stream)
        if self.navigation_input is None:
            if self.input_stream is None:
                self.input_stream = sys.stdin
            self.navigation_input = _navigation_input(self.input_stream)

    @property
    def mode(self) -> TerminalOutputMode | None:
        return self._mode

    def start(self, document: ReportDocument, command: str) -> None:
        with self._submission_lock:
            if self._dispatcher_thread is not None:
                raise RuntimeError("terminal renderer has already started")
            capabilities = self._capabilities()
            self._mode = (
                TerminalOutputMode.FLOW
                if (
                    self.force_flow
                    or self.verbosity < 0
                    or not self.actions
                    or not capabilities.supports_live
                )
                else TerminalOutputMode.LIVE
            )
            self._command = command
            self._start_document = document
            self._accepting = True
            self._dispatcher_thread = Thread(
                target=self._dispatch,
                name="poly-terminal",
                daemon=True,
            )
            self._dispatcher_thread.start()
        self._dispatcher_ready.wait()
        self._raise_dispatcher_error()

    def handle(self, event: RunEvent) -> None:
        completed = Event()
        with self._submission_lock:
            if not self._accepting:
                return
            self._commands.put(_EventCommand(event, completed))
        completed.wait()
        self._raise_dispatcher_error()

    def finish(self, document: ReportDocument, exit_code: int) -> None:
        completed = Event()
        with self._submission_lock:
            if not self._accepting:
                return
            self._accepting = False
            self._commands.put(_FinishCommand(document, exit_code, completed))
        completed.wait()
        self._join_dispatcher()
        self._raise_dispatcher_error()

    def abort(self) -> None:
        completed = Event()
        with self._submission_lock:
            if not self._accepting:
                return
            self._accepting = False
            self._commands.put(_AbortCommand(completed))
        completed.wait()
        self._join_dispatcher()
        self._raise_dispatcher_error()

    def _dispatch(self) -> None:
        try:
            self._begin()
            self._dispatcher_ready.set()
            while True:
                try:
                    timeout = 1.0 if self._mode is TerminalOutputMode.LIVE else None
                    command = self._commands.get(timeout=timeout)
                except Empty:
                    now = time.monotonic()
                    if self._next_refresh_at is not None and now >= self._next_refresh_at:
                        self._paint_live()
                        self._next_refresh_at = now + 1.0
                    continue
                try:
                    if isinstance(command, _NavigationCommand):
                        self._navigate(command.key)
                    elif isinstance(command, _EventCommand):
                        self._handle_event(command.event)
                    elif isinstance(command, _FinishCommand):
                        self._finish(command.document, command.exit_code)
                        return
                    else:
                        self._abort()
                        return
                finally:
                    if not isinstance(command, _NavigationCommand):
                        command.completed.set()
                    self._commands.task_done()
        except BaseException as error:
            self._dispatcher_error = error
            self._dispatcher_ready.set()
            self._release_waiters()
            self._restore_terminal_after_error()
        finally:
            self._stop_navigation()
            self._closed = True
            self._accepting = False

    def _begin(self) -> None:
        assert self._start_document is not None
        capabilities = self._capabilities()
        self._elapsed_started = time.monotonic()
        self._next_refresh_at = self._elapsed_started + 1.0
        self._progress_active = bool(
            capabilities.native_progress and self.actions and self.verbosity >= 0
        )
        if self._progress_active:
            self._write(_native_progress_sequence(1, 0))
        start = render_cli_start(
            self._start_document,
            self._command,
            verbosity=self.verbosity,
            color=self.color,
            width=capabilities.width,
        )
        self._start_lines = tuple(start.rstrip("\n").splitlines())
        initial_capacity = max(1, capabilities.height - len(self._start_lines) - 1)
        context_wraps = any(len(line) > capabilities.width for line in self._start_lines)
        self._compact_live = len(self.actions) > initial_capacity or context_wraps
        self._live_start_lines = () if self._compact_live else self._start_lines
        if self._mode is TerminalOutputMode.LIVE:
            try:
                self._write(_ENTER_ALTERNATE_SCREEN)
                assert self.navigation_input is not None
                try:
                    self._navigation_active = self.navigation_input.start()
                except Exception:
                    self._navigation_active = False
                self._start_navigation_reader()
                self._paint_live()
            except Exception:
                self._stop_navigation()
                self._write(_RESET_STYLE + _LEAVE_ALTERNATE_SCREEN)
                self._mode = TerminalOutputMode.FLOW
                self._write(start)
        else:
            self._write(start)

    def _handle_event(self, event: RunEvent) -> None:
        if self._closed or self.verbosity < 0:
            return
        terminal = event.state in {
            ActionState.SUCCEEDED,
            ActionState.FAILED,
            ActionState.BLOCKED,
            ActionState.INTERRUPTED,
        }
        self._record_progress(event)
        if self._mode is TerminalOutputMode.FLOW:
            if terminal:
                self._write(self._render_event(event) + self._native_progress_update(event))
            return
        if event.state is not ActionState.RUNNING and not terminal:
            return
        rendered = self._render_event(event).rstrip("\n")
        if rendered:
            self._rows[event.action_id] = rendered
            self._states[event.action_id] = event.state
            self._rebuild_live_pages()
            self._paint_live(event)

    def _finish(self, document: ReportDocument, exit_code: int) -> None:
        capabilities = self._capabilities()
        clear_progress = _native_progress_sequence(0, 0) if self._progress_active else ""
        if self._mode is TerminalOutputMode.LIVE:
            self._stop_navigation()
            self._write(_RESET_STYLE + _LEAVE_ALTERNATE_SCREEN)
            self._write(
                render_cli(
                    document,
                    self._command,
                    verbosity=self.verbosity,
                    color=self.color,
                    exit_code=exit_code,
                    width=capabilities.width,
                    hyperlinks=capabilities.hyperlinks,
                )
            )
        else:
            self._write(
                render_cli_completion(
                    document,
                    verbosity=self.verbosity,
                    color=self.color,
                    exit_code=exit_code,
                    width=capabilities.width,
                    hyperlinks=capabilities.hyperlinks,
                )
            )
        self._write(clear_progress)
        self._progress_active = False

    def _abort(self) -> None:
        clear_progress = _native_progress_sequence(0, 0) if self._progress_active else ""
        if self._mode is TerminalOutputMode.LIVE:
            self._stop_navigation()
            self._write(_RESET_STYLE + _LEAVE_ALTERNATE_SCREEN + self._aborted_history())
        elif self._mode is TerminalOutputMode.FLOW:
            self._write(f"  ✗ ABORTED  {self._command}\n")
        self._write(clear_progress + _RESET_STYLE + "\n")
        self._progress_active = False

    def _aborted_history(self) -> str:
        lines = [*self._start_lines]
        for action in self.actions:
            rendered = self._rows.get(action.id)
            if rendered:
                lines.extend(rendered.splitlines())
            else:
                lines.append(f"    · PENDING  {action.id} ({action.operation})")
        lines.append(f"  ✗ ABORTED  {self._command}")
        return "\n".join(lines) + "\n"

    def _paint_live(self, event: RunEvent | None = None) -> None:
        if self._mode is not TerminalOutputMode.LIVE or self._closed:
            return
        page_count = len(self._live_pages)
        if self._follow_last_page:
            self._current_page = page_count - 1
        self._current_page = min(max(0, self._current_page), page_count - 1)
        page = self._live_pages[self._current_page]

        footer: list[str] = []
        if page_count > 1:
            navigation = ""
            if self._navigation_active:
                mode = "FOLLOW" if self._follow_last_page else "MANUAL · F FOLLOW"
                navigation = f" · P/N PAGE · {mode}"
            footer.append(f"  PAGE {self._current_page + 1}/{page_count}{navigation}")
        footer.append(self._inline_progress().rstrip("\n"))
        occupied = len(self._live_start_lines) + len(page) + len(footer)
        padding = ("",) * max(0, self._capabilities().height - occupied)
        frame = [*self._live_start_lines, *page, *padding, *footer]
        progress = self._native_progress_update(event) if event is not None else ""
        layout = (self._current_page, page_count, bool(self._live_start_lines))
        page_changed = self._painted_layout is not None and layout != self._painted_layout
        cursor = _CLEAR_SCREEN if not self._live_painted or page_changed else _HOME_CURSOR
        rendered_frame = (_CLEAR_LINE_TO_END + "\n").join(frame) + _CLEAR_LINE_TO_END
        self._write(cursor + rendered_frame + _CLEAR_TO_END + progress)
        self._live_painted = True
        self._painted_layout = layout

    def _rebuild_live_pages(self) -> None:
        capabilities = self._capabilities()
        flattened: list[str] = []
        for _, row in self._ordered_rows():
            flattened.extend(row.splitlines())

        full_capacity = max(1, capabilities.height - len(self._start_lines) - 1)
        self._compact_live = self._compact_live or len(flattened) > full_capacity
        self._live_start_lines = () if self._compact_live else self._start_lines
        base_capacity = max(1, capabilities.height - len(self._live_start_lines) - 1)
        paginated = len(flattened) > base_capacity
        page_capacity = max(1, base_capacity - 1) if paginated else base_capacity
        pages = tuple(
            tuple(flattened[first : first + page_capacity])
            for first in range(0, len(flattened), page_capacity)
        )
        self._live_pages = pages or ((),)

    def _ordered_rows(self) -> list[tuple[str, str]]:
        order = {action.id: index for index, action in enumerate(self.actions)}
        return sorted(
            self._rows.items(),
            key=lambda item: (
                self._states.get(item[0]) is ActionState.RUNNING,
                order.get(item[0], len(order)),
                item[0],
            ),
        )

    def _start_navigation_reader(self) -> None:
        if not self._navigation_active:
            return
        self._navigation_stop.clear()
        self._navigation_thread = Thread(
            target=self._read_navigation,
            name="poly-terminal-input",
            daemon=True,
        )
        self._navigation_thread.start()

    def _read_navigation(self) -> None:
        assert self.navigation_input is not None
        while not self._navigation_stop.wait(0.01):
            try:
                key = self.navigation_input.read()
            except Exception:
                self._commands.put(_NavigationCommand(None))
                return
            if key is not None:
                self._commands.put(_NavigationCommand(key))

    def _navigate(self, key: NavigationKey | None) -> None:
        if key is None:
            self._stop_navigation()
        elif key is NavigationKey.FOLLOW:
            self._follow_last_page = True
        else:
            self._follow_last_page = False
            change = -1 if key is NavigationKey.PREVIOUS else 1
            self._current_page += change
        page_count = len(self._live_pages)
        self._current_page = min(max(0, self._current_page), page_count - 1)
        self._paint_live()

    def _stop_navigation(self) -> None:
        if not self._navigation_active or self.navigation_input is None:
            return
        self._navigation_stop.set()
        if self._navigation_thread is not None:
            self._navigation_thread.join(timeout=1.0)
            self._navigation_thread = None
        try:
            self.navigation_input.stop()
        except Exception:
            pass
        finally:
            self._navigation_active = False

    def _render_event(self, event: RunEvent) -> str:
        actions = {action.id: action for action in self.actions}
        return render_cli_event(
            event,
            actions.get(event.action_id),
            verbosity=self.verbosity,
            color=self.color,
            width=self._capabilities().width,
        )

    def _record_progress(self, event: RunEvent) -> None:
        if event.state not in {
            ActionState.SUCCEEDED,
            ActionState.FAILED,
            ActionState.BLOCKED,
            ActionState.INTERRUPTED,
        }:
            return
        action_ids = {action.id for action in self.actions}
        if event.action_id in action_ids:
            self._completed_action_ids.add(event.action_id)
        self._failed = self._failed or event.state is ActionState.FAILED
        self._blocked = self._blocked or event.state is ActionState.BLOCKED
        self._blocked = self._blocked or event.state is ActionState.INTERRUPTED

    def _native_progress_update(self, event: RunEvent) -> str:
        if not self._progress_active or event.state not in {
            ActionState.SUCCEEDED,
            ActionState.FAILED,
            ActionState.BLOCKED,
            ActionState.INTERRUPTED,
        }:
            return ""
        percentage = len(self._completed_action_ids) * 100 // max(1, len(self.actions))
        state = 2 if self._failed else 4 if self._blocked else 1
        return _native_progress_sequence(state, percentage)

    def _inline_progress(self) -> str:
        elapsed_ms = 0
        if self._elapsed_started is not None:
            elapsed_ms = round((time.monotonic() - self._elapsed_started) * 1000)
        return render_cli_progress(
            len(self._completed_action_ids),
            len(self.actions),
            failed=self._failed,
            blocked=self._blocked,
            color=self.color,
            width=self._capabilities().width,
            elapsed_ms=elapsed_ms,
            occurred_at=datetime.now(UTC).isoformat(),
        )

    def _release_waiters(self) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except Empty:
                return
            if not isinstance(command, _NavigationCommand):
                command.completed.set()
            self._commands.task_done()

    def _restore_terminal_after_error(self) -> None:
        try:
            self._stop_navigation()
            if self._mode is TerminalOutputMode.LIVE:
                self.stream.write(_RESET_STYLE + _LEAVE_ALTERNATE_SCREEN)
            if self._progress_active:
                self.stream.write(_native_progress_sequence(0, 0))
            self.stream.flush()
        except Exception:
            pass

    def _raise_dispatcher_error(self) -> None:
        if self._dispatcher_error is not None:
            raise RuntimeError("terminal rendering failed") from self._dispatcher_error

    def _join_dispatcher(self) -> None:
        if self._dispatcher_thread is not None:
            self._dispatcher_thread.join(timeout=5.0)
            if self._dispatcher_thread.is_alive():
                raise RuntimeError("terminal renderer did not stop")

    def _capabilities(self) -> TerminalCapabilities:
        assert self.capabilities is not None
        return self.capabilities

    def _write(self, value: str) -> None:
        if value:
            self.stream.write(value)
            self.stream.flush()


def _native_progress_sequence(state: int, percentage: int) -> str:
    return f"\x1b]9;4;{state};{percentage}\x07"
