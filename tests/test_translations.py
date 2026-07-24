"""Tests for French user-facing labels while controller codes remain stable."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.openems_zero_injection.controller import display_label


def test_french_translation_keys_exist_for_controller_entities() -> None:
    """Both source and French files provide the controller entity labels."""
    component = Path(__file__).parents[1] / "custom_components" / "openems_zero_injection"
    source = json.loads((component / "strings.json").read_text())
    french = json.loads((component / "translations" / "fr.json").read_text())
    for platform, key in (
        ("sensor", "controller_state"),
        ("sensor", "scheduler_state"),
        ("sensor", "current_limit"),
        ("sensor", "current_limit_source"),
        ("sensor", "ports_synchronization"),
        ("sensor", "calculated_limit"),
        ("sensor", "commanded_limit"),
        ("sensor", "last_simulated_limit"),
        ("sensor", "simulated_limit"),
        ("sensor", "waiting_state"),
        ("sensor", "last_decision"),
        ("sensor", "last_command_result"),
        ("sensor", "commands_simulated"),
        ("sensor", "trace_mode"),
        ("sensor", "trace_session_active"),
        ("sensor", "trace_data_coverage_percent"),
        ("sensor", "trace_commands_confirmed"),
        ("sensor", "trace_commands_effective"),
        ("sensor", "trace_commands_ineffective"),
        ("sensor", "trace_commands_indeterminate"),
        ("select", "controller_mode"),
    ):
        assert source["entity"][platform][key]["name"]
        assert french["entity"][platform][key]["name"]


def test_internal_codes_have_french_display_labels() -> None:
    """Translation is a presentation concern: internal codes remain English."""
    assert display_label("Grid import") == "Consommation sur le réseau"
    assert display_label("Waiting for stabilization") == "Attente de stabilisation"
    assert (
        display_label("Simulation awaiting significant measurements")
        == "Simulation en attente de nouvelles mesures significatives"
    )
    assert display_label("Command simulated") == "Commande simulée"
    assert display_label("Disabled") == "Manuel"
    assert display_label("Grid import") != "Grid import"
