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


def test_planned_block_uses_default_heading_white_gutter_magenta_body_and_bottom_rule() -> None:
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

    assert lines[1].startswith("\x1b[37m│\x1b[0m  \x1b[35m○ PLANNED  poly add\x1b[0m")
    assert lines[2].startswith("\x1b[37m│\x1b[0m    \x1b[35m75 commands in current plan\x1b[0m")
    assert lines[3].startswith(
        "\x1b[37m│\x1b[0m    \x1b[35mRun `poly exec` when the plan is ready.\x1b[0m"
    )
    assert lines[4].startswith("\x1b[37m")
    assert "─" in lines[4]
    assert len(lines) == 5


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


def test_progress_label_uses_in_progress_in_all_states() -> None:
    assert "IN PROGRESS" in render_cli_progress(2, 10, width=80)
    assert "IN PROGRESS WARN" in render_cli_progress(2, 10, blocked=True, width=80)
    assert "IN PROGRESS KO" in render_cli_progress(2, 10, failed=True, width=80)
    assert "PLAN" not in render_cli_progress(2, 10, width=80)
