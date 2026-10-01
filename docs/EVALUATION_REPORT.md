# Evaluation report — reset semantics

- Parser smoke cases: 5/5 routed to the intended query family.
- Golden question file: 168 deterministic cases generated from the canonical entity set.
- Canonical integrity: 3 farmers, 3 farms, 6 zones, 3 devices, 3 days, timezone `Asia/Ho_Chi_Minh`.
- Authorization: server-side device authorization remains mandatory; cross-farm IDs are rejected before data reads.
- No-data policy: missing/stale/unknown states are preserved and rendered as uncertainty, never as zero.
- ML acceptance: no production model is claimed. Forecast/failure/anomaly ML remain blocked until real, sufficiently long data passes held-out evaluation.

The full pytest suite could not be run in this environment because the local Python dependency mount denied access to pytest. Python compilation and direct parser/renderer smoke tests passed. Docker Compose syntax passed; Docker daemon access was unavailable in this session.
