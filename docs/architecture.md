# Build004 architecture

```text
Home Assistant grid sensor -> AcquisitionEngine -> Decision Engine
                                               -> SafetyScheduler -> DTU coordinator -> Modbus TCP
                                                          |                    |
                                                    History/Learning      0xD007/0xD00D/0xD013
```

- `acquisition.py` validates the selected local grid sensor and sign convention.
- `decision.py` is a pure, deterministic and side-effect-free calculation.
- `scheduler.py` serializes commands and applies the stabilization delay.
- `controller.py` orchestrates the modes and safety checks.
- `history.py` keeps a bounded 200-record decision history.
- `learning.py` records confirmed commands passively. It changes no parameter.
- `coordinator.py` remains the only DTU integration boundary and performs the
  verified three-register write sequence.

The controller loop runs every three seconds but does not poll Modbus. Regular
DTU telemetry remains managed by the existing 10-second coordinator update.
