# Build001 Specification

**Project:** OpenEMS Zero Injection

**Version:** V0.1-alpha

**Build:** 001

**Status:** APPROVED

---

# Objective

Develop the first installable version of the Home Assistant integration.

This build establishes the project foundation only.

No zero-injection logic must be implemented in this build.

---

# Target Environment

- Home Assistant 2026.7.2
- Python version compatible with Home Assistant
- DTU: Hoymiles DTU Pro-S
- Communication: Modbus TCP
- Default port: 502

---

# Scope

Build001 only provides the communication layer and Home Assistant integration.

It must be installable and configurable from the Home Assistant UI.

---

# Required Files

The following files shall exist and be complete:

```text
custom_components/
└── openems_zero_injection/
    ├── __init__.py
    ├── manifest.json
    ├── const.py
    ├── config_flow.py
    ├── coordinator.py
    ├── modbus.py
    ├── sensor.py
    ├── diagnostics.py
    ├── strings.json
    └── translations/
         └── fr.json
```

---

# Functional Requirements

## Integration

The integration must appear in:

Settings

→ Devices & Services

→ Add Integration

---

## Configuration Flow

The Config Flow shall request:

- DTU IP address
- Modbus TCP port

Default port:

502

Configuration must create a Config Entry.

---

## DataUpdateCoordinator

A Home Assistant DataUpdateCoordinator shall be implemented.

Responsibilities:

- Maintain Modbus connection
- Periodically check DTU availability
- Handle reconnection
- Expose connection state

No business logic.

---

## Modbus Client

Implement a dedicated Modbus TCP client.

Responsibilities:

- Open connection
- Close connection
- Check connectivity
- Read one safe register (or perform a minimal connectivity check)

No write operation.

No power limitation.

No inverter control.

---

## Sensor

Create one diagnostic sensor.

Name:

OpenEMS Connection

Possible values:

- Connected
- Disconnected

---

## Diagnostics

Implement Home Assistant diagnostics.

Expose:

- DTU IP
- Port
- Connection status
- Last communication error (if any)

Do not expose sensitive information.

---

## Logging

Use Home Assistant logging.

Typical messages:

- Connecting to DTU...
- Connected.
- Connection lost.
- Reconnecting...
- Connection failed.

---

# Explicitly Forbidden

The following features shall NOT exist in Build001:

- Zero Injection
- Power limitation
- PID controller
- Controller logic
- Smart Meter support
- SolarFlow support
- Battery management
- Forecasting
- Optimization
- Automatic decisions
- Modbus write requests
- Any algorithm adjusting inverter power

---

# Documentation

Update:

- README.md
- CHANGELOG.md

README must contain:

- Project description
- Installation
- Configuration
- Current Build
- Roadmap

---

# Tests

Provide unit tests for:

- Config Flow
- Coordinator
- Modbus client (mocked)
- Sensor

All tests must pass.

---

# Acceptance Criteria

Build001 is accepted only if:

- Integration installs successfully.
- Appears in "Add Integration".
- Config Flow works.
- Config Entry is created.
- Coordinator starts correctly.
- DTU connectivity is verified.
- Diagnostic sensor is created.
- Diagnostics work.
- No Home Assistant startup errors.
- Tests pass successfully.

---

# Deliverables

At the end of the implementation:

1. Execute the test suite.
2. Correct all detected errors.
3. Display the final project tree.
4. Display the list of created and modified files.
5. Prepare a Git commit with the message:

```text
Build001 RC1
```

Do not implement any feature planned for Build002 or later.
