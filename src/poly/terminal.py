"""Serialized terminal ownership for streamed Poly runs."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from threading import Lock
from typing import TextIO

from poly.model import ActionSpec
from poly.reporting import (
    ReportDocument,
    render_cli_completion,
    render_cli_event,
    render_cli_start,
)
from poly.runtime import ActionState, RunEvent


@dataclass(frozen=True, slots=True)
class TerminalCapabilities:
    interactive: bool
    cursor_updates: bool
    hyperlinks: bool
    width: int
    native_progress: bool = False

    @classmethod
    def detect(cls, stream: TextIO) -> TerminalCapabilities:
        interactive = stream.isatty()
        term = os.environ.get("TERM", "")
        cursor_updates = interactive and term.lower() != "dumb"
        hyperlinks = cursor_updates and "CI" not in os.environ
        terminal_program = os.environ.get("TERM_PROGRAM", "").lower()
        native_progress = (
            cursor_updates
            and "CI" not in os.environ
            and "TMUX" not in os.environ
            and (terminal_program == "iterm.app" or bool(os.environ.get("WT_SESSION")))
        )
        width = shutil.get_terminal_size(fallback=(72, 24)).columns
        return cls(interactive, cursor_updates, hyperlinks, width, native_progress)


@dataclass(slots=True)
class SerializedRunRenderer:
    """Own every streamed write and keep one visual row per action."""

    stream: TextIO
    actions: tuple[ActionSpec, ...]
    verbosity: int = 0
    color: bool = False
    capabilities: TerminalCapabilities | None = None
    _rows: dict[str, str] = field(default_factory=dict, init=False)
    _rendered_line_count: int = field(default=0, init=False)
    _completed_action_ids: set[str] = field(default_factory=set, init=False)
    _failed: bool = field(default=False, init=False)
    _blocked: bool = field(default=False, init=False)
    _progress_active: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    def __post_init__(self) -> None:
        if self.capabilities is None:
            self.capabilities = TerminalCapabilities.detect(self.stream)

    def start(self, document: ReportDocument, command: str) -> None:
        capabilities = self._capabilities()
        progress = ""
        if capabilities.native_progress and self.actions:
            self._progress_active = True
            progress = _native_progress_sequence(1, 0)
        self._write(
            progress
            + render_cli_start(
                document,
                command,
                verbosity=self.verbosity,
                color=self.color,
                width=capabilities.width,
            )
        )

    def handle(self, event: RunEvent) -> None:
        if self._closed or self.verbosity < 0:
            return
        terminal = event.state in {
            ActionState.SUCCEEDED,
            ActionState.FAILED,
            ActionState.BLOCKED,
        }
        capabilities = self._capabilities()
        if not capabilities.cursor_updates and not terminal:
            return
        if capabilities.cursor_updates and event.state is not ActionState.RUNNING and not terminal:
            return
        actions = {action.id: action for action in self.actions}
        rendered = render_cli_event(
            event,
            actions.get(event.action_id),
            verbosity=self.verbosity,
            color=self.color,
            width=capabilities.width,
        ).rstrip("\n")
        if not rendered:
            return
        if not capabilities.cursor_updates:
            self._write(rendered + "\n" + self._progress_update(event))
            return
        with self._lock:
            self._rows[event.action_id] = rendered
            order = {action.id: index for index, action in enumerate(self.actions)}
            rows = [
                row
                for action_id, row in sorted(
                    self._rows.items(), key=lambda item: (order.get(item[0], len(order)), item[0])
                )
            ]
            prefix = f"\x1b[{self._rendered_line_count}A\x1b[J" if self._rendered_line_count else ""
            progress = self._progress_update(event)
            self.stream.write(prefix + "\n".join(rows) + "\n" + progress)
            self.stream.flush()
            self._rendered_line_count = sum(len(row.splitlines()) for row in rows)

    def finish(self, document: ReportDocument, exit_code: int) -> None:
        capabilities = self._capabilities()
        clear_progress = _native_progress_sequence(0, 0) if self._progress_active else ""
        self._write(
            render_cli_completion(
                document,
                verbosity=self.verbosity,
                color=self.color,
                exit_code=exit_code,
                width=capabilities.width,
                hyperlinks=capabilities.hyperlinks,
            )
            + clear_progress
        )
        self._progress_active = False
        self._closed = True

    def abort(self) -> None:
        if not self._closed and self._capabilities().interactive:
            clear_progress = _native_progress_sequence(0, 0) if self._progress_active else ""
            self._write(clear_progress + "\x1b[0m\n")
            self._progress_active = False
        self._closed = True

    def _progress_update(self, event: RunEvent) -> str:
        if not self._progress_active or event.state not in {
            ActionState.SUCCEEDED,
            ActionState.FAILED,
            ActionState.BLOCKED,
        }:
            return ""
        action_ids = {action.id for action in self.actions}
        if event.action_id in action_ids:
            self._completed_action_ids.add(event.action_id)
        self._failed = self._failed or event.state is ActionState.FAILED
        self._blocked = self._blocked or event.state is ActionState.BLOCKED
        percentage = len(self._completed_action_ids) * 100 // len(self.actions)
        state = 2 if self._failed else 4 if self._blocked else 1
        return _native_progress_sequence(state, percentage)

    def _capabilities(self) -> TerminalCapabilities:
        assert self.capabilities is not None
        return self.capabilities

    def _write(self, value: str) -> None:
        if value:
            with self._lock:
                self.stream.write(value)
                self.stream.flush()


def _native_progress_sequence(state: int, percentage: int) -> str:
    return f"\x1b]9;4;{state};{percentage}\x07"
