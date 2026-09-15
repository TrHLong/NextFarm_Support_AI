# Hợp đồng tích hợp dữ liệu NextFarm — bản nháp để hai bên ký duyệt

## Nguyên tắc

- Endpoint qua gateway: `POST /api/telemetry/integrations/nextfarm/ingest`.
- Header: `X-Ingest-Api-Key`; production dùng secret riêng `NEXTFARM_INGEST_KEY`, không dùng token người dùng.
- `packet_id` là idempotency key ổn định. Gửi lại cùng ID trả `duplicate` và không chèn readings lần hai.
- `data_origin` ở packet và từng reading phải là `nextfarm_api`; không cho client đổi provenance giữa packet.
- `farm_id`, `zone_id`, `sensor_id`, đơn vị và metric phải được map/duyệt trước. Foreign key lỗi được audit và request thất bại.
- Mọi lần gọi đều được ghi `ops_db.ingest_attempts` với `accepted`, `duplicate`, `rejected` hoặc `error`.

## Payload telemetry mẫu

```json
{
  "packet_id": "nextfarm-gateway-01-20260815T101500Z-42",
  "message_type": "telemetry",
  "farm_id": "farm_long",
  "zone_id": "zone_long_a",
  "sent_at": "2026-08-15T10:15:00+07:00",
  "data_origin": "nextfarm_api",
  "source_dataset": "nextfarm-production-api-v1",
  "readings": [
    {
      "sensor_id": "sensor_long_a_moisture",
      "metric_type": "soil_moisture",
      "value": 62.4,
      "unit": "%",
      "quality": "good",
      "observed_at": "2026-08-15T10:14:58+07:00",
      "data_origin": "nextfarm_api"
    }
  ]
}
```

Phản hồi thành công:

```json
{"status":"accepted","packet_id":"nextfarm-gateway-01-20260815T101500Z-42","inserted_readings":1}
```

Phản hồi retry cùng packet:

```json
{"status":"duplicate","packet_id":"nextfarm-gateway-01-20260815T101500Z-42","inserted_readings":0}
```

## Payload trạng thái thiết bị mẫu

```json
{
  "packet_id": "nextfarm-controller-01-status-20260815T101505Z",
  "message_type": "device_status",
  "farm_id": "farm_long",
  "zone_id": "zone_long_a",
  "sent_at": "2026-08-15T10:15:05+07:00",
  "observed_at": "2026-08-15T10:15:04+07:00",
  "data_origin": "nextfarm_api",
  "statuses": [
    {
      "device_id": "device_long_controller",
      "port_id": "port_long_1",
      "online": true,
      "running": false,
      "last_seen_at": "2026-08-15T10:15:04+07:00"
    }
  ]
}
```

## Việc hai bên phải chốt trước pilot

1. ID mapping và ai là system of record cho farm/zone/device/port/sensor.
2. Enum metric, đơn vị chuẩn, precision, timezone và ngưỡng vật lý.
3. Rate limit, batch size, timeout, retry/backoff và retention.
4. Freshness SLA cho sensor/status và xử lý dữ liệu đến muộn/out-of-order.
5. Cách ký request hoặc mTLS; API key hiện tại phù hợp PoC nhưng production nên có rotation và gateway rate limit.
6. Quyền truy cập, dữ liệu cá nhân, log redaction, RPO/RTO và quy trình incident.

Endpoint hiện là **ingest read-only** đối với thiết bị: nó chỉ ghi dữ liệu vào hệ thống hỗ trợ, không gửi lệnh điều khiển xuống NextFarm.
