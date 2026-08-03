# 03. Kế hoạch build lại từ đầu

## Giai đoạn 1: Nghiên cứu và thiết kế lõi

- Hoàn thành đọc hiểu 9 nền tảng NextFarm.
- Chốt vai trò chatbot: tư vấn công khai, trợ lý vườn xác minh, SupportOps ticket.
- Thiết kế schema dữ liệu: khách hàng, farm, lô/khu, thiết bị, sensor, lịch tưới, cảnh báo, tri thức, ticket.
- Thiết kế bộ câu hỏi test theo từng nhóm người dùng.

## Giai đoạn 2: Dựng database và kho tri thức

- PostgreSQL làm trụ sở dữ liệu chính.
- Schema tách nhóm: identity, farm_data, knowledge, ai_model, support.
- Seed dữ liệu Anh Long theo một câu chuyện nông dân thật: cà chua nhà màng Lâm Đồng, nhiều khu tưới, cảm biến, van, lịch tưới, cảnh báo.
- Seed knowledge từ nền tảng NextFarm và runbook kỹ thuật.

## Giai đoạn 3: Dựng chatbot lõi

- Intent classifier: nhận diện câu hỏi tư vấn, dữ liệu vườn, sự cố, điều khiển, ticket.
- RAG tri thức: trả lời về nền tảng và kỹ thuật dựa trên tài liệu đã kiểm duyệt.
- Tool calling nội bộ: gọi farm-data, forecast, ticket khi cần.
- Guardrail: chống bịa, phân quyền, xác nhận lệnh điều khiển.

## Giai đoạn 4: Dựng web app mobile-first

- Màn nhập thông tin giống luồng NextFarm nhưng nhẹ hơn.
- Khách mới: chat tư vấn tự do.
- Khách đã xác minh: chat + thẻ số liệu vườn + cảnh báo + biểu đồ.
- Giao diện ưu tiên điện thoại, chữ rõ, nút dễ bấm.

## Giai đoạn 5: Demo và báo cáo

- Test theo kịch bản khách mới và Anh Long.
- Đo pass/fail theo bài toán A: chống bịa/tri thức.
- Đo pass/fail theo bài toán B: dữ liệu IoT realtime và dự báo.
- Xuất báo cáo và slide theo quá trình làm.
