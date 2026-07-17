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

Disabled and Simulation never transmit Modbus writes. Production additionally
requires **Enable Manual DTU Writes** to be on. It writes only temporary
registers `0xD007`, `0xD00D`, and `0xD013` with function `0x06`, then reads all
three with `0x03` and requires exact confirmation. Permanent and global
registers are never automatic write targets.
