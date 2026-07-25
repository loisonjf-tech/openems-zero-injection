# Build004 - Zero Injection Controller Foundation

Build004 introduces an experimental controller foundation for the Hoymiles DTU
Pro-S. It has no SolarFlow, Zendure, battery, forecast, PID, or adaptive
control logic.

The controller uses a Home Assistant grid-power entity. Its default convention
is positive = grid import and negative = export. The default target is `-40 W`
with a `30 W` deadband. The pure V1 calculation is:

```text
error = grid_power - target_grid_power
correction_percent = error / watts_per_percent
new_limit = bounded(current_limit + correction_percent)
```

The first controller implementation limits each command to 5 %, retains a
minimum 12-second stabilization interval, and requires three valid grid
measurements after an interruption.

> **Warning:** Build004 is experimental. Production mode can modify real
> photovoltaic power. Initial tests must be supervised.

Manual and Simulation never transmit automatic Modbus writes. Production writes
only temporary registers `0xD007`, `0xD00D`, and `0xD013` with function `0x06`,
then verifies the three-port result according to the configured safety mode.
Permanent and global registers are never automatic write targets.

## RC4 — Trace Recorder Timeline and Session Report

RC4 adds passive observability only. It does not alter the controller decision,
the Scheduler, stabilization timing, Modbus register set or polling cadence.

- The last 100 detailed command timelines remain in an in-memory circular buffer.
- A timeline is versioned and serializable with primitives only. It separates
  decision inputs from post-command observations and records policy, context,
  rationale, Modbus timings, per-port outcomes, confirmation and evaluation.
- Session metrics are aggregated independently from the detailed buffer, so
  session counts and averages remain complete after more than 100 commands.
- Median metrics use a bounded in-memory reservoir. Coverage is interval
  weighted and explicitly reported.
- The recorder never starts a task, polls the DTU, emits a Modbus frame, writes
  to disk, or supplies control input to the Scheduler.
