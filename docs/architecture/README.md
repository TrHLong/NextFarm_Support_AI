# Kiến trúc tổng thể và luồng dữ liệu — NextFarm AI Support V10.1

Tài liệu này được dựng từ source V10 trong gói dự án, không phải sơ đồ giả định.

## Các sơ đồ

- `00-overall-architecture.svg/.dot`: kiến trúc tổng thể.
- `01-auth-ui-flow.svg/.dot`: đăng nhập, phân quyền và frontend proxy.
- `02-telemetry-flow.svg/.dot`: simulator/NextFarm → MQTT/HTTPS → ingestion → PostgreSQL.
- `03-farm-data-flow.svg/.dot`: truy vấn realtime/Data Studio.
- `04-ai-ml-flow.svg/.dot`: dataset → train → model registry/artifact → inference/evidence.
- `05-chat-rag-truth-flow.svg/.dot`: chatbot → planner → tool layer/RAG → verbalizer → Truth Guard.
- `06-crop-router-encyclopedia-flow.svg/.dot`: farm/zone → crop_key → capability readiness.
- `07-knowledge-flow.svg/.dot`: Knowledge Studio ingest/retrieve/RAG.
- `08-ticket-support-flow.svg/.dot`: đề xuất ticket → xác nhận → kỹ thuật viên → phản hồi.
- `09-v10.1-acceptance-flow.svg/.png`: luồng bắt buộc Identity/Context → multi-tool → evidence merge → Truth Guard → trả lời hoặc safe error.

## Data stores chính

PostgreSQL dùng chung nhưng phân schema: `user_db`, `farm_db`, `knowledge_db`, `support_db`, `ops_db`, `research_db`, `ai_db`. MQTT dùng Mosquitto. Model runtime nằm trong `model-artifacts`; V10.1 đóng gói đủ 10 model V2.1 cùng báo cáo đồng bộ.

## Quy ước gói Parquet

Các bảng dữ liệu tĩnh/lịch sử đóng gói được chuyển từ CSV sang Parquet. Raw CSV chỉ còn được nhắc trong provenance của nguồn ngoài; endpoint `studio/export.csv` vẫn giữ vì đó là chức năng export cho người dùng, không phải định dạng lưu trữ nội bộ.
