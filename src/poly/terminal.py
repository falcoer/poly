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

    @classmethod
    def detect(cls, stream: TextIO) -> TerminalCapabilities:
        interactive = stream.isatty()
        term = os.environ.get("TERM", "")
        cursor_updates = interactive and term.lower() != "dumb"
        hyperlinks = cursor_updates and "CI" not in os.environ
        width = shutil.get_terminal_size(fallback=(72, 24)).columns
        return cls(interactive, cursor_updates, hyperlinks, width)


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
    _closed: bool = field(default=False, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    def __post_init__(self) -> None:
        if self.capabilities is None:
            self.capabilities = TerminalCapabilities.detect(self.stream)

    def start(self, document: ReportDocument, command: str) -> None:
        capabilities = self._capabilities()
        self._write(
            render_cli_start(
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
            self._write(rendered + "\n")
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
            self.stream.write(prefix + "\n".join(rows) + "\n")
            self.stream.flush()
            self._rendered_line_count = sum(len(row.splitlines()) for row in rows)

    def finish(self, document: ReportDocument, exit_code: int) -> None:
        capabilities = self._capabilities()
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
        self._closed = True

    def abort(self) -> None:
        if not self._closed and self._capabilities().interactive:
            self._write("\x1b[0m\n")
        self._closed = True

    def _capabilities(self) -> TerminalCapabilities:
        assert self.capabilities is not None
        return self.capabilities

    def _write(self, value: str) -> None:
        if value:
            with self._lock:
                self.stream.write(value)
                self.stream.flush()
