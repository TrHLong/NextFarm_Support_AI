# NextFarm SupportOps Chatbot

Dự án được khởi động lại từ đầu để đi đúng hướng công ty: trước hết hiểu hệ sinh thái NextFarm, sau đó mới thiết kế chatbot hỗ trợ nông dân/khách hàng.

## Nguyên tắc mới

1. Chatbot không chỉ tra dữ liệu IoT. Chatbot phải hiểu NextFarm là một hệ sinh thái gồm GIS, tưới thông minh, NMC, Fertikit, Management, Yield, QR Check, AI sâu bệnh và Weather.
2. Khách mới được hỏi tự nhiên về giải pháp, lợi ích, rủi ro, quy trình triển khai, thiết bị cần lắp và chi phí/khả năng mở rộng.
3. Khách hàng đã xác minh mới được đọc dữ liệu riêng của vườn.
4. Khi thiếu dữ liệu, chatbot nói rõ thiếu gì, cần kiểm tra gì, và chỉ chuyển ticket khi thật sự cần.
5. Dữ liệu và AI phải tách lớp để sau này công ty thay dữ liệu thật vào mà không phá kiến trúc.

## Cấu trúc sạch

- `docs/`: tài liệu nghiên cứu, định hướng sản phẩm, kiến trúc và báo cáo.
- `data/`: dữ liệu demo, dữ liệu tri thức, dữ liệu mô phỏng nông trại.
- `models/`: từng nhóm model AI riêng: intent, RAG/rerank, forecast, alert, recommendation.
- `services/`: backend/microservices sau khi chốt hướng.
- `apps/`: web app/mobile-first UI cho nông dân và màn quản trị demo khi cần.
- `infra/`: Docker, database schema, seed, gateway, monitoring.

## Bước hiện tại

Hoàn thiện tài liệu đọc hiểu nền tảng NextFarm và hướng chatbot trước khi viết lại code.
