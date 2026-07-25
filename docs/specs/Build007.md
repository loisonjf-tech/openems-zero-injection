# Build007 — Battery Priority Simulation

## Objective

Build007 compares a generic `BatteryPriorityStrategy` with the established
`ZeroInjectionStrategy` without changing Production control.

## Safety boundary

- Production always uses `ZeroInjectionStrategy`.
- `BatteryPriorityStrategy` is evaluated only in Simulation.
- It issues no battery command, DTU command, Modbus request, task or polling.
- The Predictive Controller receives the unchanged Zero Injection target.

## Candidate calculation

With `T = target_grid_power_w`, `R = remaining_charge_power_w`, and both
configured bounds equal to `25 W`:

```text
reserve_w = min(R, 25 W, 25 W)
candidate_target_grid_power_w = T - reserve_w
T - 25 W <= candidate_target_grid_power_w <= T
```

Negative grid power represents injection. The candidate is a bounded policy
target only: `R` is a potential local battery absorption capacity, not an
observed charge and not a guaranteed reduction of injection. The Trace Recorder
stores `candidate_expected_storage_gain_w = reserve_w` as a theoretical value.

## Strict fallback

The candidate exactly equals `T` with a stable fallback code when no battery is
present; data is unavailable, stale, inconsistent or faulted; capacity is
unknown or partial; the battery is full from a reliable capacity or explicit
state; or the configured target is not export-oriented.

## Diagnostics and trace

Diagnostics expose the effective target, candidate target, delta, expected
storage gain, eligible resources and fallback reason. Trace Recorder keeps a
bounded passive comparison history. No historical Scheduler or controller field
is changed.
