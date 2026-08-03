# 05. Kịch bản dữ liệu Anh Long

## Mục tiêu

Anh Long là khách hàng demo đầu tiên để kiểm tra toàn bộ luồng chatbot theo đề bài NextFarm: chống bịa, truy dữ liệu IoT realtime đúng quyền, giải thích sự cố và tạo ticket khi thiếu dữ liệu.

## Hồ sơ khách hàng

| Thuộc tính | Giá trị demo |
|---|---|
| Tên | Anh Long |
| Số điện thoại | 0327555203 |
| Vai trò | Chủ vườn/khách hàng |
| Khu vực | Lâm Đồng |
| Thiết bị chính | Điện thoại |
| Ngôn ngữ | Tiếng Việt đời thường, có thuật ngữ nông nghiệp |

## Vườn demo

| Thuộc tính | Giá trị demo |
|---|---|
| Tên vườn | Trang trại Lâm Đồng 01 |
| Cây trồng | Cà chua nhà màng |
| Diện tích | 1.8 ha |
| Phân khu GIS | A, B, C, D, E, F |
| Mô hình tưới | Tưới nhỏ giọt, chia khu theo van |
| Nền tảng liên quan | GIS, Tưới thông minh, NMC, Fertikit, Management, Weather, QR Check, Yield, AI sâu bệnh |

## Thiết bị và cảm biến

| Nhóm | Dữ liệu demo |
|---|---|
| Bộ điều khiển tưới | 2 bộ ESP32: một bản 4 cổng, một bản 3 cổng |
| Van/cổng | Van khu A-F, bơm tổng, van châm phân |
| NMC | Một node quan trắc vi khí hậu trong nhà màng |
| Fertikit | Bộ châm phân theo EC/pH |
| Cảm biến | Độ ẩm đất, nhiệt độ, EC, pH, lưu lượng, nhiệt độ/độ ẩm không khí, ánh sáng |
| Kết nối | MQTT qua Wi-Fi/Ethernet |

## Câu chuyện vận hành trong ngày

1. Buổi sáng hệ thống tưới khu A và B theo lịch.
2. Khu A giữ độ ẩm ổn định trong ngưỡng mục tiêu.
3. Khu B giảm ẩm nhanh dù có lịch tưới, nghi ngờ đầu nhỏ giọt hoặc tưới không đều.
4. NMC ghi nhận nhà màng nóng vào buổi trưa, cần chú ý stress nhiệt.
5. Fertikit chạy ca châm phân nhẹ, EC/pH trong vùng chấp nhận.
6. Khu E có cảm biến trễ dữ liệu, chatbot không được đoán số hiện tại.
7. Nếu hỏi van chưa cấu hình, chatbot phải nói chưa có trong DB.
8. Nếu hỏi điều khiển van, chatbot tạo lệnh nháp và yêu cầu xác nhận.

## Dữ liệu phục vụ bài toán A

- Knowledge article về NextFarm, GIS, tưới, NMC, Fertikit, Weather, QR, Yield, AI sâu bệnh.
- Glossary: NMC, GIS, EC, pH, MQTT, Modbus, VietGAP.
- Local aliases: béc, đầu nhỏ giọt, van lì, cây héo, đất khô.
- Evaluation set chống bịa: câu hỏi ngoài dữ liệu, câu hỏi chưa có cấu hình, câu hỏi kê phân/thuốc.

## Dữ liệu phục vụ bài toán B

- Mapping phone 0327555203 -> user Anh Long -> farm_lamdong_01.
- Zone A-F trên GIS.
- Sensor readings theo thời gian.
- Device status realtime.
- Irrigation schedules và irrigation runs.
- Alerts: thiếu nước khu B, sensor câm/trễ, NMC nóng.
- Device commands dạng draft/confirmed/sent.
