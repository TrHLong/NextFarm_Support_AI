# Data seed direction

Dữ liệu demo sẽ không bắt đầu bằng CSV rời rạc. Ta sẽ seed vào PostgreSQL theo câu chuyện người dùng.

## Nhân vật demo đầu tiên

- Khách hàng: Anh Long
- Khu vực: Lâm Đồng
- Mô hình: cà chua nhà màng
- Diện tích: 1.8 ha
- Nền tảng liên quan: GIS, Tưới thông minh, NMC, Fertikit, Management, Weather, QR Check, Yield, AI sâu bệnh

## Dữ liệu cần seed cho Anh Long

1. Hồ sơ user và quyền truy cập farm.
2. Farm và các zone A-F.
3. Thiết bị ESP32 4 cổng, van/bơm tương ứng.
4. Sensor độ ẩm đất, nhiệt độ, EC, pH, lưu lượng.
5. Lịch tưới và lịch sử tưới nhiều ngày.
6. Cảnh báo: khu B thiếu nước, sensor câm, gateway trễ dữ liệu.
7. Tri thức nền tảng NextFarm và runbook kỹ thuật.
8. Ticket mẫu đã đóng để tạo kho tri thức xử lý sự cố.
9. Dataset train/test cho intent, retrieval, forecast, alert/root-cause.
