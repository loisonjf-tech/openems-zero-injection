# Build004 controller operation

Choose the grid sensor from the integration options. If its sign convention is
opposite, enable inversion in the options.

The mode starts as **Disabled** after every Home Assistant restart:

- **Disabled**: no control calculation and no write.
- **Simulation**: calculates and records a theoretical command, but sends no
  Modbus frame.
- **Production**: may write only if the Build003 manual-write interlock is on,
  three valid grid readings were observed, all three temporary limits agree,
  and the safety scheduler allows a command.

The scheduler waits 12 seconds by default after a confirmed command because
the real DTU response is expected after approximately 10-12 seconds. A failed
command enters `Error`; no automatic retry or restore write is attempted.
