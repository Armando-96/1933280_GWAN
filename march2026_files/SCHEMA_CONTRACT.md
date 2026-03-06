# Mars IoT Simulator Schema Contracts

- Contract version: `1.2.0`
  - Policy: `fixed`
  - Discovery endpoint: `GET /api/discovery`

The provided schemas OpenAPI-like `type/required/properties` structure.

## REST Sensors

### `rest.scalar.v1` (greenhouse_temperature, entrance_humidity, co2_hall, corridor_pressure)
```json
{
  "type": "object",
  "required": ["sensor_id", "captured_at", "metric", "value", "unit", "status"],
  "properties": {
    "sensor_id": { "type": "string" },
    "captured_at": { "type": "string", "format": "date-time" },
    "metric": { "type": "string" },
    "value": { "type": "number" },
    "unit": { "type": "string" },
    "status": { "type": "string", "enum": ["ok", "warning"] }
  }
}
```

### `rest.chemistry.v1` (hydroponic_ph, air_quality_voc)
```json
{
  "type": "object",
  "required": ["sensor_id", "captured_at", "measurements", "status"],
  "properties": {
    "sensor_id": { "type": "string" },
    "captured_at": { "type": "string", "format": "date-time" },
    "measurements": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["metric", "value", "unit"],
        "properties": {
          "metric": { "type": "string" },
          "value": { "type": "number" },
          "unit": { "type": "string" }
        }
      }
    },
    "status": { "type": "string", "enum": ["ok", "warning"] }
  }
}
```

### `rest.particulate.v1` (air_quality_pm25)
```json
{
  "type": "object",
  "required": ["sensor_id", "captured_at", "pm1_ug_m3", "pm25_ug_m3", "pm10_ug_m3", "status"],
  "properties": {
    "sensor_id": { "type": "string" },
    "captured_at": { "type": "string", "format": "date-time" },
    "pm1_ug_m3": { "type": "number" },
    "pm25_ug_m3": { "type": "number" },
    "pm10_ug_m3": { "type": "number" },
    "status": { "type": "string", "enum": ["ok", "warning"] }
  }
}
```

### `rest.level.v1` (water_tank_level)
```json
{
  "type": "object",
  "required": ["sensor_id", "captured_at", "level_pct", "level_liters", "status"],
  "properties": {
    "sensor_id": { "type": "string" },
    "captured_at": { "type": "string", "format": "date-time" },
    "level_pct": { "type": "number" },
    "level_liters": { "type": "number" },
    "status": { "type": "string", "enum": ["ok", "warning"] }
  }
}
```

## Telemetry Topics (Pub/Sub)

SSE transport:
- `GET /api/telemetry/stream/{topic}`
  - Event type: `telemetry`
  - Each event `data:` is a JSON object matching the topic schema.

WebSocket transport:
- `WS /api/telemetry/ws?topic={topic}`
  - Each message is one JSON object matching the topic schema.

### `topic.power.v1` (mars/telemetry/solar_array, mars/telemetry/power_bus, mars/telemetry/power_consumption)
```json
{
  "type": "object",
  "required": ["topic", "event_time", "subsystem", "power_kw", "voltage_v", "current_a", "cumulative_kwh"],
  "properties": {
    "topic": { "type": "string" },
    "event_time": { "type": "string", "format": "date-time" },
    "subsystem": { "type": "string" },
    "power_kw": { "type": "number" },
    "voltage_v": { "type": "number" },
    "current_a": { "type": "number" },
    "cumulative_kwh": { "type": "number" }
  }
}
```

### `topic.environment.v1` (mars/telemetry/radiation, mars/telemetry/life_support)
```json
{
  "type": "object",
  "required": ["topic", "event_time", "source", "measurements", "status"],
  "properties": {
    "topic": { "type": "string" },
    "event_time": { "type": "string", "format": "date-time" },
    "source": {
      "type": "object",
      "required": ["system", "segment"],
      "properties": {
        "system": { "type": "string" },
        "segment": { "type": "string" }
      }
    },
    "measurements": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["metric", "value", "unit"],
        "properties": {
          "metric": { "type": "string" },
          "value": { "type": "number" },
          "unit": { "type": "string" }
        }
      }
    },
    "status": { "type": "string", "enum": ["ok", "warning"] }
  }
}
```

### `topic.thermal_loop.v1` (mars/telemetry/thermal_loop)
```json
{
  "type": "object",
  "required": ["topic", "event_time", "loop", "temperature_c", "flow_l_min", "status"],
  "properties": {
    "topic": { "type": "string" },
    "event_time": { "type": "string", "format": "date-time" },
    "loop": { "type": "string" },
    "temperature_c": { "type": "number" },
    "flow_l_min": { "type": "number" },
    "status": { "type": "string", "enum": ["ok", "warning"] }
  }
}
```

### `topic.airlock.v1` (mars/telemetry/airlock)
```json
{
  "type": "object",
  "required": ["topic", "event_time", "airlock_id", "cycles_per_hour", "last_state"],
  "properties": {
    "topic": { "type": "string" },
    "event_time": { "type": "string", "format": "date-time" },
    "airlock_id": { "type": "string" },
    "cycles_per_hour": { "type": "number" },
    "last_state": { "type": "string", "enum": ["IDLE", "PRESSURIZING", "DEPRESSURIZING"] }
  }
}
```

## Actuator APIs

### Request Schema (`POST /api/actuators/{actuator_name}`)
```json
{
  "type": "object",
  "required": ["state"],
  "properties": {
    "state": { "type": "string", "enum": ["ON", "OFF"] }
  }
}
```

### Response Schema
```json
{
  "type": "object",
  "required": ["actuator", "state", "updated_at"],
  "properties": {
    "actuator": { "type": "string" },
    "state": { "type": "string", "enum": ["ON", "OFF"] },
    "updated_at": { "type": "string", "format": "date-time" }
  }
}
```

### Actuator list (`GET /api/actuators`)
```json
{
  "type": "object",
  "required": ["actuators"],
  "properties": {
    "actuators": {
      "type": "object",
      "additionalProperties": { "type": "string", "enum": ["ON", "OFF"] }
    }
  }
}
```
