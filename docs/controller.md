# Build004 controller operation

> This historical Build004 behavior overview is superseded by
> [Architecture Specification](Architecture-Specification.md), the project's
> official architecture reference for future evolution.

Choose the grid sensor from the integration options. If its sign convention is
opposite, enable inversion in the options.

The mode starts as **Disabled** after every Home Assistant restart:

- **Disabled**: no control calculation and no write.
- **Simulation**: calculates and records a theoretical command, but sends no
  Modbus frame.
- **Production**: may write only if the Build003 manual-write interlock is on,
  three valid grid readings were observed, all three temporary limits agree,
  all three temporary limits were refreshed successfully in the current cycle,
  and the safety scheduler allows a command.

The scheduler waits 12 seconds by default after a confirmed command because
the real DTU response is expected after approximately 10-12 seconds. A failed
command enters `Error`; no automatic retry or restore write is attempted.

The controller uses the manually configured `installed_nominal_power_w` only.
Its conversion coefficient is always `installed_nominal_power_w / 100`; it is
never inferred from instant DTU power and is never replaced by a DTU value.
The Simulation mode uses this same coefficient with its separate virtual limit.

An isolated temporary-limit read error retains the last confirmed value for
diagnostics, marked as stale, but pauses Production. The next normal cycle
performs the next read attempt. Permanent limit registers are diagnostic only
and read at startup then every five minutes; their availability does not affect
Simulation or Production.

## Trace Recorder (Build004 RC3)

The Trace Recorder is an observer, not a control component. It receives only
snapshots and Modbus write outcomes that the controller and coordinator already
have. It owns no Modbus client, timer, scheduler lock, retry loop, or persistent
storage. Normal mode retains a circular in-memory buffer of 100 command traces.

Every trace distinguishes `timestamp_utc`, `monotonic_ms`, `source_timestamp`
and `observed_timestamp`. This prevents a Home Assistant chart timestamp from
being confused with the original measurement timestamp or an elapsed duration.
The recorder evaluates outcomes only when coverage is sufficient; otherwise it
reports `indeterminate`. RC3 intentionally does not add diagnostic polling or
exports; those belong to RC4.
