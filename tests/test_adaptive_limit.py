"""Tests for the strictly passive AdaptiveLimitModel."""

from datetime import UTC, datetime, timedelta

from custom_components.openems_zero_injection.adaptive_limit import (
    AdaptiveLimitConfidence,
    AdaptiveLimitModel,
    AdaptiveObservationRejection,
)


def _observe_confirmed_command(
    model: AdaptiveLimitModel,
    *,
    timestamp: datetime,
    before_limit: int = 13,
    after_limit: int = 18,
    before_power: float = 900,
    first_power: float = 1100,
    second_power: float = 1120,
    battery_signature: tuple[object, ...] = (),
):
    model.record_baseline(
        timestamp=timestamp - timedelta(seconds=20),
        power_w=before_power,
        grid_power_w=-100,
        battery_signature=battery_signature,
    )
    model.record_baseline(
        timestamp=timestamp - timedelta(seconds=10),
        power_w=before_power,
        grid_power_w=-100,
        battery_signature=battery_signature,
    )
    model.register_confirmed_command(
        timestamp=timestamp,
        limit_before_percent=before_limit,
        limit_after_percent=after_limit,
        power_before_w=before_power,
        battery_signature=battery_signature,
    )
    assert model.observe(
        timestamp=timestamp + timedelta(seconds=12),
        power_w=first_power,
        scheduler_stabilizing=False,
        battery_signature=battery_signature,
    ) is None
    return model.observe(
        timestamp=timestamp + timedelta(seconds=20),
        power_w=second_power,
        scheduler_stabilizing=False,
        battery_signature=battery_signature,
    )


def test_confirmed_stable_command_builds_a_local_gain_profile() -> None:
    """A stable, signed command response is accepted but remains passive."""
    model = AdaptiveLimitModel(nominal_gain_w_per_percent=30)
    observation = _observe_confirmed_command(
        model, timestamp=datetime(2026, 8, 8, tzinfo=UTC)
    )

    assert observation is not None
    assert observation.accepted
    assert observation.gain_observed_w_per_percent == 42
    profile = model.profile_for(18, now=datetime(2026, 8, 8, tzinfo=UTC))
    assert profile.limit_range == "11-25"
    assert profile.estimated_gain_w_per_percent == 42
    assert profile.confidence is AdaptiveLimitConfidence.INSUFFICIENT
    # One sample cannot create an adaptive candidate. The controller still
    # uses 30 W/% irrespective of model confidence.
    candidate = model.candidate_for(current_limit_percent=18, grid_error_w=-84)
    assert candidate.limit_candidate_percent is None
    assert model.diagnostics()["gain_used_w_per_percent"] == 30


def test_unstable_post_command_power_is_indeterminate_not_zero_gain() -> None:
    """Solar variation after a command cannot become a false calibration point."""
    model = AdaptiveLimitModel(nominal_gain_w_per_percent=30)
    observation = _observe_confirmed_command(
        model,
        timestamp=datetime(2026, 8, 8, tzinfo=UTC),
        first_power=980,
        second_power=1250,
    )

    assert observation is not None
    assert not observation.accepted
    assert observation.gain_observed_w_per_percent is None
    assert (
        observation.rejection_reason
        is AdaptiveObservationRejection.POST_POWER_UNSTABLE
    )
    assert model.profile_for(18).accepted_observations == 0


def test_unstable_pre_command_context_is_rejected_before_waiting() -> None:
    """A changing PV or grid baseline is not safe evidence of command effect."""
    model = AdaptiveLimitModel(nominal_gain_w_per_percent=30)
    timestamp = datetime(2026, 8, 8, tzinfo=UTC)
    model.record_baseline(
        timestamp=timestamp - timedelta(seconds=20),
        power_w=800,
        grid_power_w=-100,
        battery_signature=(),
    )
    model.record_baseline(
        timestamp=timestamp - timedelta(seconds=10),
        power_w=1000,
        grid_power_w=-100,
        battery_signature=(),
    )

    model.register_confirmed_command(
        timestamp=timestamp,
        limit_before_percent=13,
        limit_after_percent=18,
        power_before_w=1000,
        battery_signature=(),
    )

    observation = model.last_observation
    assert observation is not None
    assert not observation.accepted
    assert (
        observation.rejection_reason
        is AdaptiveObservationRejection.PRE_COMMAND_MEASUREMENTS_UNSTABLE
    )


def test_battery_transition_rejects_the_command_effect() -> None:
    """A battery change prevents attributing a PV change to the DTU command."""
    model = AdaptiveLimitModel(nominal_gain_w_per_percent=30)
    started = datetime(2026, 8, 8, tzinfo=UTC)
    model.record_baseline(
        timestamp=started - timedelta(seconds=20),
        power_w=1000,
        grid_power_w=-100,
        battery_signature=("healthy", 0.0, 0.0),
    )
    model.record_baseline(
        timestamp=started - timedelta(seconds=10),
        power_w=1000,
        grid_power_w=-100,
        battery_signature=("healthy", 0.0, 0.0),
    )
    model.register_confirmed_command(
        timestamp=started,
        limit_before_percent=30,
        limit_after_percent=35,
        power_before_w=1000,
        battery_signature=("healthy", 0.0, 0.0),
    )
    observation = model.observe(
        timestamp=started + timedelta(seconds=15),
        power_w=1150,
        scheduler_stabilizing=False,
        battery_signature=("healthy", 250.0, 0.0),
    )

    assert observation is not None
    assert not observation.accepted
    assert (
        observation.rejection_reason
        is AdaptiveObservationRejection.BATTERY_CONTEXT_CHANGED
    )


def test_median_and_confidence_are_local_to_the_limit_range() -> None:
    """Eight coherent gains establish medium confidence only in their range."""
    model = AdaptiveLimitModel(nominal_gain_w_per_percent=30)
    started = datetime(2026, 8, 8, tzinfo=UTC)
    for index, power_after in enumerate(
        (1100, 1110, 1120, 1110, 1090, 1100, 1110, 1120)
    ):
        _observe_confirmed_command(
            model,
            timestamp=started + timedelta(minutes=index * 2),
            first_power=power_after,
            second_power=power_after,
        )

    trained = model.profile_for(18)
    untouched = model.profile_for(60)
    assert trained.accepted_observations == 8
    assert trained.confidence is AdaptiveLimitConfidence.MEDIUM
    assert trained.estimated_gain_w_per_percent is not None
    assert untouched.accepted_observations == 0
    assert untouched.estimated_gain_w_per_percent is None
    assert untouched.confidence is AdaptiveLimitConfidence.NONE


def test_prediction_is_scored_before_its_observation_is_learned() -> None:
    """The fourth result evaluates the three prior gains, never itself."""
    model = AdaptiveLimitModel(nominal_gain_w_per_percent=30)
    started = datetime(2026, 8, 8, tzinfo=UTC)
    for index in range(3):
        _observe_confirmed_command(
            model, timestamp=started + timedelta(minutes=index * 2)
        )

    observation = _observe_confirmed_command(
        model,
        timestamp=started + timedelta(minutes=8),
        first_power=1200,
        second_power=1200,
    )

    assert observation is not None
    assert observation.accepted
    assert observation.prediction_comparable
    assert observation.adaptive_gain_before_observation_w_per_percent == 42
    assert observation.predicted_nominal_power_change_w == 150
    assert observation.predicted_adaptive_power_change_w == 210
    assert observation.observed_power_change_w == 300
    assert observation.nominal_error_w == 150
    assert observation.adaptive_error_w == 90
    assert observation.adaptive_model_better is True
    metrics = model.prediction_metrics("11-25")
    assert metrics["comparable_predictions"] == 1
    assert metrics["adaptive_better_percent"] == 100


def test_nominal_power_change_discards_incomparable_observations() -> None:
    """The passive profile cannot mix observations across user PV reconfiguration."""
    model = AdaptiveLimitModel(nominal_gain_w_per_percent=30)
    _observe_confirmed_command(model, timestamp=datetime(2026, 8, 8, tzinfo=UTC))

    model.reset(nominal_gain_w_per_percent=40)

    assert model.profile_for(18).accepted_observations == 0
    assert model.diagnostics()["gain_nominal_w_per_percent"] == 40
