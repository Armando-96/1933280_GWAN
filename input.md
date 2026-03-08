# SYSTEM DESCRIPTION:

## USER STORIES:

### Real-Time Monitoring & Telemetry

1) As a Mars Operator, I want to view a list of all available sensors in the habitat, so that I know what data is currently being monitored.

2) As a Mars Operator, I want to see the real-time value of the greenhouse_temperature, so that I can ensure the crops survive the Martian night.

3) As a Mars Operator, I want to view the latest PM2.5, PM10, and PM1 air quality metrics together, so that I can monitor the safety of the breathable air.

4) As a Mars Operator, I want to visually distinguish sensors that have a "warning" status, so that I can immediately react to hardware anomalies.

5) As a Mars Operator, I want to see the timestamp of the last received measurement for each sensor, so that I know the data is fresh and the sensor is not frozen.

6) As a Mars Operator, I want to monitor the power generation of the solar arrays (kW and Voltage), so that I can ensure the habitat has enough energy.

7) As a Mars Operator, I want to monitor the thermal loop temperature and flow, so that I can prevent the core from overheating.

8) As a Mars Operator, I want to see the current state of the airlock (e.g., PRESSURIZING or DEPRESSURIZING), so that I know if it's safe to initiate an Extravehicular Activity (EVA).

9) As a Mars Operator, I want to see the unit of measurement (e.g., °C, ppm, kW) displayed clearly next to every numerical value, so that I don't misinterpret the readings.

### Actuator Manual Control
10) As a Mars Operator, I want to view the current ON/OFF state of all habitat actuators, so that I know what life-support equipment is currently running. 
11) As a Mars Operator, I want to manually toggle the habitat_heater, so that I can adjust the ambient comfort level during a sudden temperature drop. 
12) As a Mars Operator, I want to receive immediate visual feedback on the dashboard when an actuator changes state, so that I have confirmation my command was executed successfully.

### Automation Rules Management (Rule Engine)
13) As a Habitat Engineer, I want to create an automation rule using a simple "IF condition THEN action" interface, so that I can automate repetitive safety tasks.
14) As a Habitat Engineer, I want to select the target actuator and its desired state (ON/OFF) when creating a rule, so that the system knows exactly what action to take.
15) As a Habitat Engineer, I want to view a complete list of all active automation rules on the dashboard, so that I can audit the current logical behavior of the habitat. 
16) As a Habitat Engineer, I want to delete an existing automation rule, so that I can safely remove outdated logic from the system.

### Event-Driven System & Background Tasks
17) As a Mars Operator, I want the dashboard to update automatically without refreshing the page (via WebSocket or SSE), so that I never miss critical thermodynamic events.

### Dashboard Customization & UX
18) As a Mars Operator, I want to easily filter the dashboard widgets to only show sensors with a "warning" status, so that I can focus entirely on emergencies during a crisis. 
19) As a Mars Operator, I want the dashboard to show a disconnected/offline indicator if the connection to the backend drops, so that I don't trust stale dashboard data. 
20) As a Habitat Engineer, I want to see the underlying source protocol (REST or TELEMETRY) for a sensor displayed in its details, so that I can quickly debug connectivity or polling issues.

## Unified Internal Event Schema

To handle the heterogeneous devices in the Martian habitat which communicate via both REST polling and asynchronous telemetry streams with different JSON structures the ingestion layer acts as an Adapter.
It converts every raw incoming payload into a standardized **Unified Internal Event Schema**.

For complex payloads containing multiple measurements (e.g., `rest.particulate.v1` or `topic.power.v1`), the ingestion service "flattens" the original payload by generating multiple distinct unified events, one for each specific metric.

### JSON Structure

```json
{
  "sensor_id": "string",
  "timestamp": "string (ISO 8601)",
  "metric": "string",
  "value": "number | string",
  "unit": "string",
  "status": "string",
  "source_protocol": "string"
}
```

### Field Dictionary

* **`sensor_id`**: The unique identifier of the sensor or subsystem that generated the data. For REST sensors, this matches the provided ID (e.g., `greenhouse_temperature`). For telemetry, it is a composite ID combining the topic and subsystem/loop/airlock (e.g., `solar_array_array_alpha`) to guarantee uniqueness. This matches the `<sensor_name>` required by the automation engine rules.
* **`timestamp`**: The exact date and time when the measurement was captured or the event occurred, standardized in ISO 8601 UTC format.
* **`metric`**: The specific physical quantity, chemical concentration, or system state being evaluated (e.g., `temperature`, `pm25`, `voltage`, `last_state`).
* **`value`**: The actual reading. It supports `number` for standard metrics (e.g., `28.5`, `415.2`) and `string` for telemetry state enumerations (like `"PRESSURIZING"` or `"DEPRESSURIZING"` from the airlock ).
* **`unit`**: The unit of measurement associated with the value (e.g., `°C`, `ppm`, `kW`, `%`). For state enumerations, a placeholder like `state` is used.
* **`status`**: The operational health status of the device, strictly mapped to `"ok"` or `"warning"` as defined by the hardware contracts.
* **`source_protocol`**: A custom field indicating the origin of the payload, allowing the system to know if the data arrived via `REST` (polling) or `TELEMETRY` (streaming).

### Normalization Examples

#### Example 1: REST Scalar Sensor (1-to-1 Mapping)
A simple REST payload from the `co2_hall` sensor.
* **Original Payload:**
```json
{
  "sensor_id": "co2_hall",
  "captured_at": "2036-03-05T12:00:00Z",
  "metric": "co2_concentration",
  "value": 415.2,
  "unit": "ppm",
  "status": "ok"
}
```
* **Unified Event:**
```json
{
  "sensor_id": "co2_hall",
  "timestamp": "2036-03-05T12:00:00Z",
  "metric": "co2_concentration",
  "value": 415.2,
  "unit": "ppm",
  "status": "ok",
  "source_protocol": "REST"
}
```

#### Example 2: Telemetry Multi-metric Stream (1-to-Many Mapping)
A telemetry payload from the `mars/telemetry/solar_array` topic containing multiple data points.
* **Original Payload:**
```json
{
  "topic": "mars/telemetry/solar_array",
  "event_time": "2036-03-05T12:30:00Z",
  "subsystem": "array_alpha",
  "power_kw": 12.5,
  "voltage_v": 240.0,
  "current_a": 52.08,
  "cumulative_kwh": 1050.5
}
```
* **Unified Events (Published as separate messages to the broker):**
```json
[
  {
    "sensor_id": "solar_array_array_alpha",
    "timestamp": "2036-03-05T12:30:00Z",
    "metric": "power",
    "value": 12.5,
    "unit": "kW",
    "status": "ok",
    "source_protocol": "TELEMETRY"
  },
  {
    "sensor_id": "solar_array_array_alpha",
    "timestamp": "2036-03-05T12:30:00Z",
    "metric": "voltage",
    "value": 240.0,
    "unit": "V",
    "status": "ok",
    "source_protocol": "TELEMETRY"
  },
  {
    "sensor_id": "solar_array_array_alpha",
    "timestamp": "2036-03-05T12:30:00Z",
    "metric": "current",
    "value": 52.08,
    "unit": "A",
    "status": "ok",
    "source_protocol": "TELEMETRY"
  },
  {
    "sensor_id": "solar_array_array_alpha",
    "timestamp": "2036-03-05T12:30:00Z",
    "metric": "cumulative_energy",
    "value": 1050.5,
    "unit": "kWh",
    "status": "ok",
    "source_protocol": "TELEMETRY"
  }
]
```

#### Example 3: Telemetry String State (Airlock)
A telemetry payload from the `mars/telemetry/airlock` topic containing both a numerical metric and a string state.
* **Original Payload:**
```json
{
  "topic": "mars/telemetry/airlock",
  "event_time": "2036-03-05T13:15:00Z",
  "airlock_id": "main_eva_hatch",
  "cycles_per_hour": 2,
  "last_state": "DEPRESSURIZING"
}
```
* **Unified Events (Published as separate messages to the broker):**
```json
[
  {
    "sensor_id": "airlock_main_eva_hatch",
    "timestamp": "2036-03-05T13:15:00Z",
    "metric": "cycles",
    "value": 2,
    "unit": "cycles/h",
    "status": "ok",
    "source_protocol": "TELEMETRY"
  },
  {
    "sensor_id": "airlock_main_eva_hatch",
    "timestamp": "2036-03-05T13:15:00Z",
    "metric": "last_state",
    "value": "DEPRESSURIZING",
    "unit": "state",
    "status": "ok",
    "source_protocol": "TELEMETRY"
  }
]
```
