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
    english = json.loads((component / "translations" / "en.json").read_text())
    for platform, key in (
        ("sensor", "controller_state"),
        ("sensor", "scheduler_state"),
        ("sensor", "current_limit"),
        ("sensor", "current_limit_source"),
        ("sensor", "ports_synchronization"),
        ("sensor", "calculated_limit"),
        ("sensor", "commanded_limit"),
        ("sensor", "waiting_state"),
        ("sensor", "last_decision"),
        ("sensor", "last_command_result"),
        ("sensor", "trace_mode"),
        ("sensor", "trace_session_active"),
        ("sensor", "trace_data_coverage_percent"),
        ("sensor", "trace_commands_confirmed"),
        ("sensor", "trace_commands_effective"),
        ("sensor", "trace_commands_ineffective"),
        ("sensor", "trace_commands_indeterminate"),
        ("sensor", "grid_source_timestamp"),
        ("sensor", "pv_source_timestamp"),
        ("sensor", "measurement_sync_reason"),
        ("select", "controller_mode"),
    ):
        assert source["entity"][platform][key]["name"]
        assert french["entity"][platform][key]["name"]
        if key.startswith("trace_"):
            assert english["entity"][platform][key]["name"]
    assert (
        french["entity"]["sensor"]["calculated_limit"]["name"]
        == "Limite prédictive théorique"
    )


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


def test_trace_recorder_states_are_translated_without_changing_internal_codes() -> None:
    """The UI translation layer owns trace labels, not the serialized values."""
    component = Path(__file__).parents[1] / "custom_components" / "openems_zero_injection"
    source = json.loads((component / "strings.json").read_text())
    french = json.loads((component / "translations" / "fr.json").read_text())
    english = json.loads((component / "translations" / "en.json").read_text())

    for translation in (source, french, english):
        assert translation["entity"]["sensor"]["trace_mode"]["state"]["normal"]
        assert translation["entity"]["sensor"]["trace_session_active"]["state"]["active"]
        assert translation["entity"]["sensor"]["trace_session_active"]["state"]["inactive"]
