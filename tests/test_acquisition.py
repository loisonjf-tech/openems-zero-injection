"""Tests for local Home Assistant grid-power acquisition."""

from custom_components.openems_zero_injection.acquisition import AcquisitionEngine


def test_acquisition_validates_sign_and_range(hass) -> None:
    hass.states.async_set("sensor.grid", "-125.5")
    assert AcquisitionEngine(hass, "sensor.grid", False).read_grid_power().power_w == -125.5
    assert AcquisitionEngine(hass, "sensor.grid", True).read_grid_power().power_w == 125.5


def test_acquisition_rejects_invalid_and_outlier_values(hass) -> None:
    engine = AcquisitionEngine(hass, "sensor.grid", False)
    assert engine.read_grid_power().power_w is None
    hass.states.async_set("sensor.grid", "not-a-number")
    assert engine.read_grid_power().power_w is None
    hass.states.async_set("sensor.grid", "20001")
    assert engine.read_grid_power().power_w is None
