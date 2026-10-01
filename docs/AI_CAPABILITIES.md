# AI capabilities and evidence status

## Production logic

- Deterministic data retrieval and aggregation
- Vietnamese normalization and temporal resolution
- Threshold, freshness, missing-data and device rules
- Server-side authorization and fail-closed responses

## Experimental / blocked

- Moisture forecast: `BLOCKED_INSUFFICIENT_REAL_DATA`
- Early irrigation/flow failure prediction: `BLOCKED_INSUFFICIENT_REAL_DATA`
- Sensor anomaly detection: rule baselines are available; ML production status is blocked

The three-day synthetic reset is for schema, integration and query tests only. It is not production training evidence and does not justify accuracy claims.

## Active model policy

The farmer runtime does not load legacy joblib artifacts. The analytics endpoint
returns `NOT_VALIDATED` until a model passes a real-data gate, so deleting old
artifacts cannot change a farmer answer.

Only three future capabilities remain eligible for a later evidence run:

1. `moisture_forecast` — 30/60/120 minute soil-moisture forecast.
2. `flow_fault_forecast` — early no-flow risk, only after independent incidents.
3. `sensor_fault_forecast` — sensor anomaly support, after a rule baseline.

Temperature, EC, pH, leak, irrigation-need, power-loss, MQTT-loss, device-health
and farm-health models are not active farmer models. Current-state questions
use deterministic queries and rules instead.

`DEVICE_AUTO_TRAIN=false` is the default. Training is an explicit technician
operation and produces evidence outside the farmer runtime.
