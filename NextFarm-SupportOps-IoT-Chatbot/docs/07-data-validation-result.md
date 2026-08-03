# 07. Kết quả kiểm tra schema và seed dữ liệu

Ngày kiểm tra: 03/08/2026

## Cách kiểm tra

Dựng PostgreSQL container tạm bằng image `postgres:16-alpine`, chạy lần lượt:

1. `infra/database/nextfarm_supportops_schema.sql`
2. `infra/database/seed_anh_long.sql`

Sau đó query số bản ghi chính để xác nhận seed dữ liệu Anh Long đã vào đúng schema.

## Kết quả

| Nhóm dữ liệu | Số bản ghi |
|---|---:|
| users | 3 |
| farms | 1 |
| zones | 6 |
| devices | 4 |
| sensors | 11 |
| readings | 606 |
| alerts | 3 |
| knowledge_articles | 7 |
| tickets | 2 |
| models | 4 |

## Kết luận

- Schema PostgreSQL chạy được.
- Seed dữ liệu Anh Long chạy được.
- Dữ liệu đủ để bắt đầu build service đọc dữ liệu vườn, service tri thức, chatbot orchestrator và bộ test đầu tiên.
- Bài toán A đã có nền: knowledge, glossary, evaluation set, citation sau này.
- Bài toán B đã có nền: identity mapping, farm_id, zone, device, sensor readings, device status, irrigation, alerts.

## Cập nhật kiểm tra pre-sales

Sau khi bổ sung schema `sales`, chạy lại PostgreSQL container tạm với schema + seed mới.

| Nhóm dữ liệu | Số bản ghi |
|---|---:|
| customer_leads | 1 |
| sales_lead_profiles | 1 |
| sales_requirements | 1 |
| sales_recommendations | 4 |
| sales_opportunities | 1 |
| sales_proposals | 1 |
| readings | 606 |

Kết luận bổ sung:

- Khách mới chưa phải customer vẫn có luồng dữ liệu riêng.
- Chatbot có thể lưu nhu cầu, tư vấn module phù hợp và tạo cơ hội bán hàng.
- Pre-sales không trộn lẫn với dữ liệu vườn riêng của customer, nên vẫn giữ được bảo mật.
