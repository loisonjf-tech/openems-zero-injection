# Build006 — Energy Strategy Engine Foundation

## Objective

Build006 formalises the energy-strategy boundary without changing DTU control.
It introduces `EnergyStrategyEngine` and encapsulates the established target
behaviour in `ZeroInjectionStrategy`.

## Scope

- The only active strategy is `ZeroInjectionStrategy`.
- Its output is exactly the configured `target_grid_power_w` used by Build004
  RC4 and Build005.
- The strategy is pure: no Home Assistant read, Modbus request, battery
  command, task or persistent state.
- A stable `EnergyStrategyReasonCode`, decision timestamp and input snapshot
  identifier prepare tracing and replay.
- `energy_policy.py` preserves former public names as compatibility aliases.

## Explicit exclusions

- No `BatteryPriorityStrategy` implementation or activation.
- No battery data affects a decision.
- No change to `controller.py`, `scheduler.py`, `decision.py` or `modbus.py`.
- No change to predictive calculation, scheduler timing, DTU registers, writes,
  entities or options.

## Compatibility invariant

For the same configured target, Build006 returns the same target, policy
identifier, legacy explanation, confidence and fallback flag as Build005. A
deterministic test fixes the timestamp and snapshot identifier to prove this.

## Follow-up

Build007 may compare a future `BatteryPriorityStrategy` with this baseline in
Simulation and Trace Recorder only. It must not activate a battery strategy.
