"""Versioned, atomic persistence for inventories, plans, and run reports."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from poly.model import JsonValue
from poly.reporting import ReportDocument

STATE_SCHEMA = "poly.state/v1"
LEGACY_STATE_SCHEMA = "poly.state/v0"


class StateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StateStore:
    workspace: Path

    def __post_init__(self) -> None:
        workspace = self.workspace.resolve()
        if not workspace.is_dir():
            raise StateError(f"workspace does not exist: {workspace}")
        object.__setattr__(self, "workspace", workspace)

    @property
    def state_directory(self) -> Path:
        return self.workspace / ".poly" / "state"

    @property
    def runs_directory(self) -> Path:
        return self.workspace / ".poly" / "runs"

    def save_inventory(self, document: ReportDocument) -> Path:
        return self._save(self.state_directory / "inventory.json", "inventory", document)

    def save_plan(self, run_id: str, document: ReportDocument) -> Path:
        return self._save(self._run_path(run_id) / "plan.json", "plan", document)

    def save_prepared_plan(self, document: ReportDocument) -> Path:
        return self._save(self.state_directory / "plan.json", "plan", document)

    def load_prepared_plan(self) -> ReportDocument:
        return self._load(self.state_directory / "plan.json")

    def clear_prepared_plan(self) -> bool:
        path = self.state_directory / "plan.json"
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def save_run(self, run_id: str, document: ReportDocument) -> Path:
        return self._save(self._run_path(run_id) / "report.json", "run", document)

    def load_inventory(self) -> ReportDocument:
        return self._load(self.state_directory / "inventory.json")

    def load_report(self, run_id: str) -> ReportDocument:
        run_directory = self._run_path(run_id)
        report = run_directory / "report.json"
        return self._load(report if report.is_file() else run_directory / "plan.json")

    def _save(self, path: Path, kind: str, document: ReportDocument) -> Path:
        envelope: dict[str, JsonValue] = {
            "state_schema": STATE_SCHEMA,
            "kind": kind,
            "document": document,
        }
        _atomic_json(path, envelope)
        return path

    def _load(self, path: Path) -> ReportDocument:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise StateError(f"state does not exist: {path}") from error
        except (OSError, json.JSONDecodeError) as error:
            raise StateError(f"cannot read state {path}: {error}") from error
        document, migrated = _migrate(raw)
        if migrated:
            kind = str(document.get("kind", "report"))
            self._save(path, kind, document)
        return document

    def _run_path(self, run_id: str) -> Path:
        normalized = run_id.strip()
        if not normalized or any(
            character not in "-_.0123456789abcdefghijklmnopqrstuvwxyz"
            for character in normalized.lower()
        ):
            raise StateError(f"invalid run id: {run_id!r}")
        return self.runs_directory / normalized


def _migrate(value: object) -> tuple[ReportDocument, bool]:
    if not isinstance(value, dict):
        raise StateError("state root must be an object")
    state_schema = value.get("state_schema")
    if state_schema == STATE_SCHEMA:
        document = value.get("document")
        return _report_document(document), False
    if state_schema == LEGACY_STATE_SCHEMA:
        return _report_document(value.get("payload")), True
    if isinstance(value.get("schema"), str) and str(value["schema"]).startswith("poly.report/"):
        return _report_document(value), True
    raise StateError(f"unsupported state schema: {state_schema!r}")


def _report_document(value: object) -> ReportDocument:
    if not isinstance(value, dict):
        raise StateError("persisted report document must be an object")
    if value.get("schema") != "poly.report/v1" or not isinstance(value.get("kind"), str):
        raise StateError("persisted report document is incompatible")
    return value


def _atomic_json(path: Path, value: dict[str, JsonValue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
