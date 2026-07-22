# OpenEMS Zero Injection — Architecture Specification

**Status:** Reference architecture — approved design baseline  
**Scope:** V1 stable foundation and contracts for V2/V3  
**Target:** Home Assistant, Hoymiles DTU Pro-S, single-phase installation  
**Last updated:** 2026-07-22

## 1. Vision

OpenEMS Zero Injection is a local-first Home Assistant integration that limits
Hoymiles microinverter active power through a DTU Pro-S. It keeps grid exchange
near a configured target while prioritising safety, determinism and traceability.

Every automatic command must be reproducible from timestamped measurements,
configuration and the selected energy policy. A transport error, uncertain DTU
limit or unavailable battery adapter must never lead to an implicit command.

V1 is the safe DTU foundation. V2 introduces predictive control and policy
contracts. V3 introduces validated batteries and bounded calibration use.

## 2. Objectives

### Functional

- Read DTU telemetry through local Modbus TCP.
- Write only temporary per-port limits 0xD007, 0xD00D and 0xD013 when authorised.
- Keep three port limits identical for an automatic command.
- Support Manual, Simulation and Automatic Regulation modes.
- Produce deterministic and explainable power-limit decisions.
- Prepare vendor-neutral contracts for batteries and other resources.

### Non-functional

- Safety first: no automatic write with an uncertain applied limit.
- No cloud dependency for control.
- Same snapshot and configuration produce the same decision.
- All decisions, fallbacks and pauses are observable.
- Existing configuration entries, entity IDs and internal mode values remain compatible.
- Large validated deviations are handled without long artificial step chains.
- Calculation and classification modules are independently unit-testable.

## 3. Non-goals

- Cloud control, permanent DTU writes or global power-limit writes.
- Automatic retry after a failed DTU command.
- Opaque machine learning or unbounded adaptation.
- Vendor-specific battery logic inside the DTU controller.
- Treating a probable physical cause as a certain fact.

## 4. Principles

1. One owner per responsibility: client owns frames, scheduler owns command timing,
   policy owns targets.
2. Immutable inputs: a decision uses one timestamped snapshot, never mixed live data.
3. Fail closed for writes: unknown limits, desynchronised ports, transport errors
   or incoherent measurements pause automatic control.
4. Fail open for diagnostics: optional telemetry failure does not hide valid data.
5. Simulation parity: same acquisition, context, policy and calculation; no write.
6. Calibration informs but never authorises a command.
7. Battery neutrality: policies receive normalized resources, not vendor APIs.

## 5. System overview

~~~mermaid
flowchart LR
    HA["Home Assistant grid sensor"] --> A["Acquisition"]
    DTU["Hoymiles DTU Pro-S"] --> CO["DTU Coordinator"]
    CO --> A
    A --> CA["Context Analyzer"]
    CA --> CM["Calibration Manager"]
    CM --> PE["Energy Policy Engine"]
    PE --> PC["Predictive Controller"]
    PC --> SS["Safety Scheduler"]
    SS --> CO
    CO --> MC["Internal Modbus TCP Client"]
    MC --> DTU
    EM["Energy Manager / battery adapters"] --> PE
    CA --> DIAG["Diagnostics and history"]
    CM --> DIAG
    PE --> DIAG
    PC --> DIAG
    SS --> DIAG
~~~

The coordinator is the only DTU data boundary. The Modbus client is the only
component constructing Modbus frames. The scheduler is the only component that
can execute an automatic command.

## 6. Common module contracts

All contracts are immutable domain models, independent of Home Assistant entities.

~~~python
@dataclass(frozen=True, slots=True)
class ControlSnapshot:
    grid_power_w: float
    grid_timestamp: datetime
    pv_power_w: float | None
    pv_timestamp: datetime | None
    real_limit_percent: int
    limits_timestamp: datetime
    target_grid_power_w: float

@dataclass(frozen=True, slots=True)
class EnergyPolicyDecision:
    target_grid_power_w: float
    policy_id: str
    reason: str
    confidence: float
    fallback_used: bool

@dataclass(frozen=True, slots=True)
class ControlPlan:
    strategy: str
    requested_limit_percent: int | None
    reason: str
    requires_confirmation: bool
~~~

A control plan is not a command. The scheduler must validate it before Modbus
traffic is allowed.

## 7. Module responsibilities

### 7.1 Acquisition

**Purpose:** validate Home Assistant measurements and their sign, age and range.

**Input:** configured grid-power entity and optional sign inversion.

**Output:** a timestamped grid measurement plus a short ordered window of valid
samples for filtering.

**Responsibilities:**

- reject unavailable, non-numeric, stale and out-of-range states;
- apply the sign convention once and retain the source timestamp;
- provide a short median filter.

It must not poll Modbus, infer batteries, write entities or select a DTU limit.

~~~text
positive grid power = import from the grid
negative grid power = export to the grid
~~~

### 7.2 DTU Coordinator

**Purpose:** own lifecycle, telemetry cadence, Modbus health and confirmed limits.

It owns the persistent internal client, serialized refreshes, freshness and
per-register health, temporary-limit coherence/source, command confirmation and
Config Entry lifecycle. It returns measurements and health metadata; it never
chooses a desired limit.

Permanent limits 0xD008, 0xD00E and 0xD014 are optional diagnostics. Their
failure cannot block control and they are never written.

### 7.3 Context Analyzer

**Purpose:** qualify likely cause and quality of recent variation before the
controller selects a strategy.

**Input:** short window of coherent snapshots, latest confirmed command and,
later, normalized battery power.

**Output:** classification, bounded confidence and explicit reason.

~~~text
stable
consumption_step_likely
irradiance_change_likely
battery_ramp_likely
post_command_response
mixed_or_unknown
measurements_unstable
~~~

Estimated-load change with stable PV suggests consumption. PV change with stable
estimated load suggests irradiance. High variance, conflicting directions or
timestamp mismatch means unstable data. Without fresh battery telemetry, a
battery cause remains mixed or unknown.

### 7.4 Calibration Manager

**Purpose:** passively estimate installation response characteristics.

It accepts only confirmed commands and post-stabilization samples accepted by
the Context Analyzer. It produces a versioned CalibrationProfile containing a
bounded effective watts-per-percent factor, response-time statistics, residual
statistics, sample counts and confidence.

Samples are rejected during unstable measurements, irradiance changes or
unexplained battery changes. It issues no test command and cannot alter write
range, stabilization delay or safety predicates.

Profiles are stored through Home Assistant Store, not frequent Config Entry
updates. The initial mode is diagnostics-only. Use of a calibration factor is
opt-in, bounded and requires sufficient confidence.

### 7.5 Energy Manager and battery adapters

**Purpose:** maintain a read-only, vendor-neutral inventory.

V1 aggregates passive BatteryResource information. Future adapters expose
availability, state of charge, charge/discharge power, maximum charge/discharge
power and autonomous state. Adapters never call the DTU controller directly.

### 7.6 Energy Policy Engine

**Purpose:** select desired net grid exchange from an explicit policy.

**Input:** validated snapshot, context, calibration confidence, resources and
policy configuration.

**Output:** EnergyPolicyDecision. The canonical output is target_grid_power_w.
A policy must not return a Modbus address or a DTU limit.

The V1 zero-injection policy returns the configured target, normally minus 40 W.
A battery-aware policy with unavailable/low-confidence data visibly falls back
to zero injection.

### 7.7 Predictive Controller

**Purpose:** convert a policy target and coherent snapshot into a ControlPlan.

~~~text
estimated_load_w = pv_power_w + grid_power_w
target_pv_w = estimated_load_w - target_grid_power_w
predictive_limit_percent =
  clamp(round(target_pv_w / installed_nominal_power_w * 100), 2, 100)
~~~

| Strategy | Preconditions | Result |
|---|---|---|
| Predictive jump | Fresh synchronized PV, grid and limits; confirmed large deviation | Direct bounded target |
| Fine correction | Known limit; small residual error | Bounded 1–2% correction |
| Cautious correction | PV unsuitable; grid/limit still safe | Bounded 1–2% correction |
| Safety pause | Any control-critical uncertainty | No command |

Fine and cautious correction use the existing proportional rule:

~~~text
error_w = grid_power_w - target_grid_power_w
correction_percent = round(error_w / watts_per_percent)
~~~

### 7.8 Safety Scheduler

**Purpose:** serialize automatic commands and enforce timing safety.

Invariants:

- exactly one automatic command at a time;
- no command during stabilization;
- no automatic retry after a failure;
- no command when automatic-write predicates are false;
- confirmed writes update the known reference;
- large opposite changes require fresh confirmation.

### 7.9 Internal Modbus TCP Client

**Purpose:** execute the limited documented protocol safely.

It owns one persistent connection, a central async lock, MBAP validation,
transaction identifiers, 5-second timeouts, clean reconnection and error
classification. Supported operations remain 0x04 input reads, 0x03 documented
holding reads and 0x06 single temporary per-port writes. No public method writes
permanent or global limits.

## 8. Control flow

~~~mermaid
flowchart TD
    A["Validated snapshot"] --> B{"Manual mode?"}
    B -- Yes --> M["Publish only; no automatic command"]
    B -- No --> C{"Scheduler stabilizing?"}
    C -- Yes --> W["Waiting; no command"]
    C -- No --> D{"Limits certain and ports synchronized?"}
    D -- No --> P["Safety pause"]
    D -- Yes --> E{"Error within deadband?"}
    E -- Yes --> N["No action"]
    E -- No --> F{"PV/grid fresh and synchronized?"}
    F -- No --> G["Cautious fine correction"]
    F -- Yes --> H{"Large persistent error; context confirmed?"}
    H -- Yes --> I["Predictive jump"]
    H -- No --> J["Fine correction or wait confirmation"]
    G --> S["Scheduler validation"]
    I --> S
    J --> S
    S --> K{"Simulation?"}
    K -- Yes --> L["Record simulated command"]
    K -- No --> Q["Write D007, D00D, D013 and confirm"]
~~~

### Default thresholds

| Constant | Default | Purpose |
|---|---:|---|
| Grid target | minus 40 W | Small tolerated export |
| Predictive threshold | max of 250 W and four times deadband | Minimum direct-jump error |
| Fine step | 2% | Residual/cautious correction |
| Stabilization | 12 s | Physical-response wait |
| Context confirmation | 2 coherent snapshots | Reject one transient |
| Grid window | 3 samples | Median noise rejection |
| Reversal guard | 24 s | Avoid immediate opposite jump |
| Urgent import threshold | 600 W | Candidate rapid increase |

Only operationally useful thresholds become user options; the rest remain
documented constants until real-installation evidence justifies exposure.

### Oscillation prevention

No slow long average is used. The controller uses a median of three valid grid
samples, two coherent observations before a large jump, stabilization after every
command and a short large-reversal guard. Mixed/unstable context yields fine
correction or no action. The first post-command response is not treated as a
new household event.

## 9. Scheduler state machine

~~~mermaid
stateDiagram-v2
    [*] --> Inactive
    Inactive --> Ready: Automatic mode and safe snapshot
    Ready --> WaitingConfirmation: large jump needs confirmation
    WaitingConfirmation --> Ready: confirmation received
    WaitingConfirmation --> Inactive: data invalid
    Ready --> Executing: approved control plan
    Executing --> Stabilizing: three-port write confirmed
    Executing --> ErrorPaused: write or verification failure
    Stabilizing --> Ready: delay elapsed and safe snapshot
    Stabilizing --> Inactive: mode changes or data invalid
    Ready --> Inactive: manual mode, deadband or data invalid
    ErrorPaused --> Inactive: explicit rearm and valid data
    Inactive --> [*]: integration unload
~~~

ErrorPaused never performs an automatic restoration write.

## 10. Sequence diagrams

### Predictive automatic command

~~~mermaid
sequenceDiagram
    participant Grid as Grid sensor
    participant Coord as DTU Coordinator
    participant Context as Context Analyzer
    participant Policy as Policy Engine
    participant Ctrl as Predictive Controller
    participant Sched as Scheduler
    participant DTU as DTU Pro-S

    Grid->>Ctrl: validated current sample
    Coord->>Ctrl: fresh PV and coherent temporary limits
    Ctrl->>Context: recent snapshots
    Context-->>Ctrl: confirmed classification
    Ctrl->>Policy: snapshot and resources
    Policy-->>Ctrl: target grid power
    Ctrl->>Ctrl: build predictive plan
    Ctrl->>Sched: plan
    Sched->>DTU: 0x06 D007, D00D, D013
    DTU-->>Sched: exact acknowledgements
    Sched-->>Ctrl: confirmed; start stabilization
    Note over Sched,Ctrl: no automatic command during stabilization
~~~

### Simulation

~~~mermaid
sequenceDiagram
    participant Inputs as Validated inputs
    participant Ctrl as Predictive Controller
    participant Sched as Scheduler
    participant HA as Diagnostics

    Inputs->>Ctrl: same snapshot as Automatic Regulation
    Ctrl->>Sched: simulated plan
    Sched-->>Ctrl: simulated result
    Ctrl->>HA: strategy, limit, reason and timestamps
    Note over Sched: no Modbus write is constructed or sent
~~~

### Failed write

~~~mermaid
sequenceDiagram
    participant Sched as Scheduler
    participant Coord as DTU Coordinator
    participant DTU as DTU Pro-S
    participant HA as Diagnostics

    Sched->>Coord: common temporary-limit request
    Coord->>DTU: 0x06 temporary port writes
    DTU-->>Coord: transport, protocol or echo failure
    Coord-->>Sched: unconfirmed; ports uncertain
    Sched->>Sched: ErrorPaused
    Sched->>HA: explicit error; no automatic retry
~~~

## 11. Energy policies

~~~python
class EnergyPolicy(Protocol):
    def decide(
        self,
        snapshot: ControlSnapshot,
        context: ContextClassification,
        resources: EnergyManagerSnapshot,
    ) -> EnergyPolicyDecision: ...
~~~

| Policy | Status | Behavior |
|---|---|---|
| zero_injection | V1 default | Return configured grid target |
| battery_priority | V2 | Prefer validated battery absorption before PV curtailment |
| self_consumption | V2/V3 | Prefer local use within explicit constraints |
| minimize_grid_import | V3 | Favor generation/storage under policy limits |
| scheduled_tariff | V3 candidate | Apply explicit time/tariff objectives |

## 12. Diagnostics and error handling

Diagnostics must distinguish current observations from values used by the last
decision:

- current filtered grid power;
- grid/PV power and timestamps used by the last decision;
- error, estimated load, policy target, predicted and commanded limits from the
  same decision snapshot;
- strategy, context, confidence, stabilization and reversal guard;
- real-limit source, port synchronization and write result;
- Modbus health, per-register freshness and reconnect count;
- calibration confidence and sample statistics;
- active policy, reason and fallback state.

| Failure | Required behavior |
|---|---|
| TCP timeout, EOF or socket error | Close, bounded reconnect backoff, retain marked stale valid data |
| Invalid Modbus response | Mark request failed; never confirm a command |
| Optional permanent register unavailable | Mark only that diagnostic unavailable |
| Temporary limit unknown/incoherent | Pause automatic control unless valid compatibility reference applies |
| Partial three-port write | Mark uncertain; pause; explicit Manual resynchronization required |
| PV/grid timestamp mismatch | No predictive command; cautious control only if explicitly safe |
| Context unstable | Wait or fine correction; no unconfirmed large jump |
| Policy/battery unavailable | Visible fallback to zero injection |

No path replaces an unknown limit with zero, 2%, 100%, or a guess.

## 13. Test strategy

### Unit tests

- Modbus framing, timeout, reconnect, serialization, 0x03, 0x04, 0x06 and absence
  of unsupported writes.
- Register decoding, range and byte/word ordering.
- Predictive/corrective calculations, signs and clamping.
- Context classifications: appliance step, irradiance, instability, post-command
  response and missing battery data.
- Calibration sample acceptance/rejection, bounded update and confidence.
- Policy fallbacks and deterministic targets.
- Scheduler transitions, stabilization, reversal guard and failed-write pause.

### Integration and scenario tests

- Config Entry migration/options persistence and entity compatibility.
- Mode isolation, exact three-port confirmation and clean unload.
- Sustained export/import, cloud passage, appliance start/stop and DTU loss.
- Battery charge ramp once a validated adapter exists.
- Syntax, JSON and full test suite run in CI without a real DTU or external service.

## 14. Migration

- Keep Config Entry keys and internal Disabled, Simulation and Production values.
- Preserve entity IDs when visible labels change.
- Treat the existing maximum-step setting as fine-step until formal migration.
- Add options with documented defaults; never infer nominal power from DTU output.
- Existing installations retain validated behavior until predictive mode is
  explicitly enabled after Simulation validation.
- New installations may default to predictive only after hardware validation.
- Store calibration profiles separately in a versioned local store.
- Disable obsolete entities through the registry rather than deleting IDs.

Migrations must be idempotent, tested from the prior schema and safe when optional
new data is absent.

## 15. Roadmap

### V1 — Safe DTU control foundation

Robust internal Modbus client, telemetry, temporary three-port control, Manual/
Simulation/Automatic modes, scheduler, diagnostics and limit validation. UX and
safety behavior are frozen after final validation.

### V2 — Predictive and policy foundation

Synchronized snapshots, Context Analyzer, predictive controller, fine/cautious
fallback, default zero-injection policy and passive CalibrationManager diagnostics.
SolarFlow command logic is not required before adapter validation.

### V3 — Multi-resource energy management

Validated SolarFlow adapter and normalized battery snapshots, battery-priority and
self-consumption policies, opt-in bounded calibration contribution, generic
additional adapters and explicitly specified tariff policies.

## 16. Acceptance criteria

An implementation conforms to this specification only if it:

- writes solely within the documented temporary per-port register set;
- requires a safe explainable plan before each automatic command;
- keeps Simulation calculation-equivalent and write-free;
- never treats a failed or partial command as confirmed;
- exposes enough data to reconstruct the last decision;
- preserves compatibility through tested migration;
- keeps vendor-specific battery detail outside the predictive controller;
- passes automated tests and real-hardware validation appropriate to release scope.
