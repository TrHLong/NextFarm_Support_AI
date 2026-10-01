# Canonical data schema

The reset dataset uses farmer → farm → zone/device ownership and attaches `farmer_id`, `farm_id`, `device_id`, `zone_id` and an ISO-8601 timestamp wherever applicable. Tables are `farmer`, `farm`, `zone`, `device`, `sensor_reading`, `device_state`, `irrigation_schedule`, `irrigation_event`, `fertilizer_event`, `command_log` and `alert`.

Missing is not zero. A reading carries value/quality; device state distinguishes `online`, `offline` and `unknown`. Water is represented by `water_liters`, instantaneous flow by `flow_rate_lpm`, and fertilizer by `fertilizer_ml` plus `fertilizer_channel`.
