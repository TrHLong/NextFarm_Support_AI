# NextFarm V10.1.1 feedback-audited package

- Không chứa `.env`, API key, mật khẩu hoặc token.
- Có đầy đủ Web UI, 10 model V2.1, dữ liệu Parquet và sơ đồ.
- Dữ liệu `data/operational` là synthetic chỉ để kiểm thử nghiệm thu, không phải telemetry production.
- Một bộ model evidence duy nhất dùng dataset `nextfarm-v10.1-training-26d296902921`.
- Acceptance offline đạt 16/16 và 57 unit tests đạt; phải chạy runtime suite trên máy có Docker trước khi ký nghiệm thu triển khai.
- 50 ca nông học đang chờ chuyên gia NextFarm duyệt; gói chưa được đánh dấu `feedback_acceptance_ready`.

Đối chiếu chi tiết nằm tại `docs/V10.1-FEEDBACK-AUDIT.md` và
`docs/V10.1-COMPANY-REMEDIATION.md`.
