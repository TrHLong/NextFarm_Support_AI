# Chat query architecture

`question → intent/entities/time range → authorization → tool/API → deterministic result → Vietnamese rendering`

The planner distinguishes current value, list, aggregation and comparison/trend. `Trưa nay` resolves to 11:00–13:30 local time, never to the current instant. Multi-field irrigation logs remain one business query and preserve start/end, water and fertilizer fields.

Supported groups include sensor readings, device state, schedules, irrigation/fertilizer events, command logs, alerts and farm profile. Authorization is enforced below the planner using the authenticated farmer and allowed farm/device IDs.
