"""Tests for the simplified user-facing controller-mode selector."""

from custom_components.openems_zero_injection.select import OpenEMSControllerModeSelect


def test_controller_mode_selector_exposes_only_manual_and_automatic() -> None:
    """Simulation is an internal diagnostic facility, not a UI option."""
    assert OpenEMSControllerModeSelect._attr_options == [
        "Manuel",
        "Régulation automatique",
    ]
