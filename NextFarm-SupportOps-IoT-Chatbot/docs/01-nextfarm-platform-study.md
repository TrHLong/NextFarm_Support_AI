# 01. Đọc hiểu hệ sinh thái NextFarm

Nguồn nghiên cứu chính: các trang nền tảng công khai của NextFarm.

## 1. Nhận định tổng quát

NextFarm không phải một chatbot hoặc một dashboard IoT đơn lẻ. Định vị của công ty là nền tảng nông nghiệp số kết nối toàn bộ quy trình: từ bản đồ lô thửa, thiết bị IoT, tưới/châm phân, nhật ký canh tác, dự báo sản lượng, truy xuất QR, AI sâu bệnh đến thời tiết vi mô.

Vì vậy chatbot SupportOps nếu chỉ hỏi/đáp độ ẩm, van, lịch tưới thì quá hẹp. Chatbot đúng hướng phải đóng vai trò "trợ lý vận hành nông nghiệp số": vừa tư vấn sản phẩm cho khách mới, vừa hỗ trợ khách hàng đang vận hành vườn, vừa chuyển sự cố thành ticket có dữ liệu nền.

## 2. Bảng đọc hiểu từng nền tảng

| Nền tảng | Vai trò trong hệ sinh thái | Dữ liệu sinh ra / sử dụng | Chatbot cần hiểu để trả lời |
|---|---|---|---|
| Trang chủ NextFarm | Định vị chung: canh tác thông minh, truy xuất chuẩn, bán giá cao hơn | Tín hiệu tổng quan: GIS, IoT, AI, QR, VietGAP, dashboard, cảnh báo | Giải thích NextFarm là gì, vì sao không phải một công cụ lẻ, lợi ích với nông hộ/HTX/doanh nghiệp |
| Tưới thông minh | Tự động tưới theo lịch, cảm biến và thời tiết | Độ ẩm đất, trạng thái van/bơm, lịch tưới, lưu lượng nước, cảnh báo van/lỗi áp suất | Tư vấn chia khu tưới, đọc độ ẩm, kiểm tra thiếu nước, cảnh báo van, giải thích tiết kiệm nước/nhân công |
| NMC | Quan trắc vi khí hậu tại lô 24/7 | Nhiệt độ, độ ẩm không khí, ánh sáng, CO2, gió, mưa, ngưỡng cảnh báo | Giải thích vì sao số liệu tại lô khác dự báo thời tiết chung; liên hệ NMC với sâu bệnh, tưới, VietGAP |
| Fertikit | Châm phân dinh dưỡng tự động theo công thức EC/pH | Công thức dinh dưỡng, EC, pH, lịch châm phân, nhật ký phân bón | Giải thích châm phân qua hệ tưới, cảnh báo không tự kê liều nếu thiếu công thức/cây/giai đoạn |
| GIS | Nền bản đồ lô thửa và tài sản nông trại | Ranh giới lô, diện tích, mã lô, vị trí thiết bị, vị trí van/NMC | Hiểu câu hỏi theo ngữ cảnh khu/lô: "khu B", "lô L-12", "van khu A" |
| Management | Nhật ký canh tác, kế hoạch vụ mùa, giao việc, vật tư, VietGAP | Công việc, nhân công, vật tư, ảnh, GPS, thời gian, hồ sơ chứng nhận | Tư vấn quy trình ghi nhật ký, hỏi thiếu dữ liệu VietGAP, giải thích hồ sơ và tác dụng quản trị |
| Yield | Dự báo và theo dõi sản lượng | IoT, thời tiết, lịch sử vụ mùa, sản lượng thực tế | Trả lời dự báo sản lượng, độ tin cậy, điều kiện cần để dự báo tốt, kế hoạch bán/logistics |
| QR Check | Truy xuất nguồn gốc nông sản | Nhật ký canh tác, lô thửa, chứng nhận, lô hàng, lượt quét | Giải thích QR giúp minh bạch, tăng niềm tin, truy sự cố an toàn thực phẩm |
| AI sâu bệnh | Nhận diện sâu bệnh qua ảnh | Ảnh lá/thân/quả, kết quả bệnh, mức độ, hướng xử lý, lịch sử xử lý | Hướng dẫn chụp ảnh, giải thích kết quả, chuyển chuyên gia khi rủi ro cao, không kê thuốc bừa |
| Weather | Dự báo thời tiết vi mô theo lô | Dự báo 14 ngày, mưa/gió/nhiệt độ theo tọa độ, cảnh báo cực đoan | Gợi ý hoãn tưới khi sắp mưa, tránh phun thuốc trước mưa, chuẩn bị che chắn |

## 3. Cách các nền tảng liên kết với nhau

Luồng logic đúng của NextFarm:

1. GIS tạo bản đồ và định danh lô/khu.
2. IoT/NMC/Weather sinh dữ liệu thực tế và dự báo theo vị trí.
3. Irrigation/Fertikit dùng dữ liệu đó để tưới, châm phân và ghi lại lịch sử.
4. Management gom nhật ký, vật tư, công việc, ảnh và dữ liệu tự động để tạo hồ sơ VietGAP/GlobalGAP.
5. Yield dùng dữ liệu vụ mùa + IoT + thời tiết để dự báo sản lượng.
6. QR Check dùng nhật ký/lô hàng để truy xuất nguồn gốc cho người mua.
7. AI sâu bệnh dùng ảnh + dữ liệu vi khí hậu/thời tiết để hỗ trợ phát hiện và xử lý sớm.
8. SupportOps chatbot đứng ở giữa, giúp người dùng hỏi bằng ngôn ngữ tự nhiên và điều phối sang dữ liệu/ticket/model phù hợp.

## 4. Kết luận sản phẩm

Chatbot phải được thiết kế theo ba tầng năng lực:

- Tầng tư vấn công khai: trả lời cho khách mới về NextFarm, lợi ích, thiết bị, quy trình triển khai, rủi ro và cấu hình đề xuất.
- Tầng trợ lý vườn đã xác minh: đọc dữ liệu riêng của khách hàng, trả lời độ ẩm, van, lịch tưới, cảnh báo, dự báo và nguyên nhân khả dĩ.
- Tầng SupportOps: khi câu hỏi vượt dữ liệu hoặc cần người xử lý, chatbot tạo ticket có ngữ cảnh, mức ưu tiên và checklist ban đầu.
