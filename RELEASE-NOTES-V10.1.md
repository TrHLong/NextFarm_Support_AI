# NextFarm AI Support V10.1.1 — Feedback audit hardening

V10.1.1 sửa các khoảng trống được phát hiện khi đối chiếu trực tiếp với
`Review_Long_v2.docx`: benchmark đúng taxonomy 260 ca, oracle từ dữ liệu nguồn,
schema vận hành có provenance/invariants, policy zone/metric fail-closed, định
tuyến kiến thức chính xác hơn và RAG đọc được bảng HTML.

## Kết quả offline

- Unit tests: 57 passed, 0 failed.
- Static validation: 45/45; acceptance mở rộng: 16/16.
- Planner/tool argument: 240/240 ca định tuyến đúng; 20 ca ACL chấm riêng.
- Multi-source planning: 23 ca.
- Dataset: 11 bảng; 40 farm; 120 zone; 80 user; tối thiểu 700.000 readings.
- ACL offline: 50/50 truy cập chéo farm bị chặn, rò rỉ bằng 0.
- 50 câu nông học được gắn trạng thái chờ chuyên gia NextFarm.

## Chạy trên Windows

1. Mở Docker Desktop.
2. Chạy `scripts\setup_v10_env.cmd`.
3. Chạy `scripts\start_v10.cmd`.
4. Chạy `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_v10_completion.ps1 -Runtime`.

Không được coi báo cáo offline là bằng chứng runtime. Trường
`feedback_acceptance_ready` chỉ thành `true` sau khi runtime đạt và 50 ca nông học
được duyệt.
