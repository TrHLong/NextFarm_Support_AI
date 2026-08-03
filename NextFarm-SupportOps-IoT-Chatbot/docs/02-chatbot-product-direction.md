# 02. Định hướng chatbot theo chiều công ty

## 1. Vấn đề của hướng cũ

Hướng cũ sai ở chỗ coi chatbot là giao diện truy vấn dữ liệu IoT. Người dùng hỏi gì cũng bị kéo về độ ẩm, van, cảnh báo hoặc bị chặn vì chưa xác minh DB. Với nông dân hoặc khách mới, trải nghiệm này gây khó chịu vì họ cần được tư vấn trước khi bị yêu cầu hiểu hệ thống.

## 2. Hướng mới

Chatbot SupportOps phải có tư duy giống nhân viên tư vấn kiêm kỹ thuật viên cấp 1:

1. Nếu là khách mới: lắng nghe nhu cầu, hỏi quy mô vườn/cây trồng/hạ tầng hiện có, giải thích NextFarm phù hợp ra sao.
2. Nếu là khách hàng đã xác minh: dùng dữ liệu farm_id để trả lời dữ liệu riêng.
3. Nếu thiếu dữ liệu: nói rõ thiếu dữ liệu nào, ảnh hưởng gì, cần kiểm tra gì.
4. Nếu rủi ro cao hoặc cần người xử lý: tạo ticket có ngữ cảnh, không đẩy khách hàng đi gọi hotline ngay.

## 3. Các nhóm câu hỏi chatbot phải xử lý

| Nhóm câu hỏi | Ví dụ | Cách trả lời đúng |
|---|---|---|
| Tìm hiểu NextFarm | "NextFarm gồm những gì?" | Giải thích hệ sinh thái 9 nền tảng và cách chúng liên kết |
| Tư vấn triển khai | "Tôi có vườn rau 1 ha thì cần gì?" | Hỏi cây trồng, nhà màng, nguồn nước, số khu; đề xuất GIS + tưới + cảm biến + NMC/Fertikit tùy nhu cầu |
| Hỏi lợi ích kinh tế | "Lắp tưới tự động lợi gì?" | Nói bằng ngôn ngữ đời thường: giảm công tưới, giảm lãng phí nước/phân, kiểm soát từ điện thoại, có lịch sử để làm hồ sơ |
| Hỏi rủi ro | "Mất mạng thì sao?" | Giải thích offline-first/app, thiết bị/gateway, dữ liệu trễ, cơ chế cảnh báo và giới hạn PoC |
| Dữ liệu vườn | "Khu B có thiếu nước không?" | Chỉ trả lời khi xác minh khách hàng; kết hợp độ ẩm, xu hướng, van, lịch tưới, cảnh báo |
| Điều khiển thiết bị | "Bật van 2 trong 10 phút" | Kiểm tra quyền, tạo lệnh nháp, yêu cầu xác nhận, ghi nhật ký lệnh |
| Sự cố kỹ thuật | "Cảm biến không gửi dữ liệu" | Đưa checklist: nguồn, dây RS485/Modbus, MQTT, mạng, last_seen; tạo ticket nếu cần |
| Sâu bệnh/canh tác | "Lá cà chua bị đốm" | Hướng dẫn chụp ảnh, nói cần AI ảnh/chuyên gia nếu chưa đủ dữ liệu; không kê thuốc bừa |

## 4. Kiến trúc dự kiến sau khi build lại

- `identity-service`: xác minh khách hàng, mapping phone -> customer -> farm_id -> quyền truy cập.
- `knowledge-service`: kho tri thức NextFarm, tài liệu nền tảng, FAQ, runbook kỹ thuật, chính sách chống bịa.
- `conversation-orchestrator`: hiểu ý định, chọn công cụ, giữ ngữ cảnh hội thoại.
- `farm-data-service`: đọc dữ liệu vườn đã xác minh: lô, thiết bị, sensor, lịch tưới, cảnh báo.
- `ai-model-service`: intent, retrieval/rerank, forecast, alert/root-cause, recommendation.
- `ticket-service`: tạo ticket khi thiếu dữ liệu hoặc cần kỹ thuật viên.
- `web-app`: mobile-first chat app cho nông dân/khách hàng; sau mới có dashboard quản trị nếu cần demo.

## 5. Nguyên tắc trả lời của chatbot

- Nói bằng tiếng Việt đời thường.
- Thuật ngữ kỹ thuật phải giải thích trong ngoặc khi cần: EC/pH, NMC, GIS, MQTT, Modbus.
- Không nói tên bảng DB cho người dùng cuối.
- Không bịa số liệu, không bịa tính năng, không kê đơn phân/thuốc nếu thiếu nguồn kiểm duyệt.
- Có ích trước, chuyển người sau.
- Với khách mới, ưu tiên tư vấn và đặt câu hỏi làm rõ, không chặn bằng thông báo DB.
