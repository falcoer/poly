from __future__ import annotations

from poly.reporting import render_cli, render_cli_progress, render_cli_start


def _planned_add_document() -> dict[str, object]:
    return {
        "schema": "poly.report/v1",
        "kind": "prepared-commands",
        "request": {
            "verb": "add",
            "selected_node_ids": [],
            "parameters": {
                "poly.node.id": "361-admin-check-src",
                "poly.source.url": "https://example.invalid/361-admin-check-src.git",
                "poly.source.ref": "P17",
            },
        },
        "prepared": {
            "state": "planned",
            "journal_version": 2,
            "command_count": 75,
            "commands": [],
        },
    }


def _executable_plan_document() -> dict[str, object]:
    return {
        "schema": "poly.report/v1",
        "kind": "plan",
        "request": {"verb": "verify", "selected_node_ids": [], "parameters": {}},
        "plan": {
            "id": "plan-1",
            "status": "executable",
            "planned_actions": [],
            "diagnostics": [],
        },
    }


def _prepared_exec_document() -> dict[str, object]:
    return {
        "schema": "poly.report/v1",
        "kind": "prepared-plan",
        "request": {"verb": "exec", "selected_node_ids": [], "parameters": {}},
        "prepared": {
            "state": "resolved",
            "journal_version": 2,
            "command_count": 2,
            "commands": [
                {"verb": "add", "command": "poly add repository alpha"},
                {"verb": "add", "command": "poly add repository beta"},
            ],
        },
        "plan": {
            "id": "plan-1",
            "status": "executable",
            "planned_actions": [],
            "diagnostics": [],
        },
    }


def test_planned_add_uses_compact_unframed_magenta_summary() -> None:
    output = render_cli(
        _planned_add_document(),  # type: ignore[arg-type]
        "poly add repository 361-admin-check-src --prepare",
        color=True,
        width=60,
    )
    lines = output.splitlines()

    assert lines[0].startswith("ADDING 361-admin-check-src from https://example.invalid/")
    assert "\x1b[" not in lines[0]
    assert not lines[0].startswith("─")

    assert lines[1] == "  \x1b[35m○ Planned (75 commands prepared in current plan)\x1b[0m"
    assert "┌" not in output
    assert "└" not in output
    assert len(lines) == 2


def test_command_start_has_no_horizontal_rule_before_heading() -> None:
    output = render_cli_start(
        _executable_plan_document(),  # type: ignore[arg-type]
        "poly verify",
        color=False,
        width=60,
    )
    lines = output.splitlines()
    assert lines[0] == "VERIFYING ..."
    assert not lines[0].startswith("─")


def test_exec_start_uses_compact_command_count_and_numbered_commands() -> None:
    output = render_cli_start(
        _prepared_exec_document(),  # type: ignore[arg-type]
        "poly exec --jobs 12",
        color=False,
        width=100,
    )

    assert output.splitlines() == [
        "EXEC PLAN (2 commands)",
        "  1. poly add repository alpha",
        "  2. poly add repository beta",
    ]
    assert "plan-1" not in output


def test_progress_label_uses_in_progress_in_all_states() -> None:
    assert "IN PROGRESS" in render_cli_progress(2, 10, width=80)
    assert "IN PROGRESS WARN" in render_cli_progress(2, 10, blocked=True, width=80)
    assert "IN PROGRESS KO" in render_cli_progress(2, 10, failed=True, width=80)
    assert "PLAN" not in render_cli_progress(2, 10, width=80)


def test_progress_bar_is_capped_and_current_time_bracket_is_closed() -> None:
    output = render_cli_progress(
        40,
        81,
        width=120,
        elapsed_ms=322_000,
        occurred_at="2026-09-07T14:24:26Z",
    ).rstrip()
    bar = output.split("[", 1)[1].split("]", 1)[0]

    assert len(bar) == 20
    assert "[2026-09-07 " in output
    assert output.endswith("]")
    assert len(output) <= 120
