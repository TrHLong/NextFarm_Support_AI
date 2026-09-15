# Bản gọn để đưa lên GitHub - 15/09/2026

Đây là bản mã nguồn và bằng chứng chọn lọc của NextFarm V13, **không phải bản sao lưu đầy đủ 7 GB**. Dự án gốc và toàn bộ CSV lớn vẫn nằm tại `D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1`, không bị xóa hay sửa khi đóng gói.

## Bản này giữ gì?

| Thành phần | Được giữ |
| --- | --- |
| Web và backend | Mã nguồn ứng dụng, Docker Compose, Dockerfile, schema/seed, cấu hình mẫu, script khởi động |
| Kiểm thử | Bộ `tests_device`, ngân hàng 130 câu, 25 đối chiếu số liệu và báo cáo V13 |
| Bốn model dự báo mới | Đủ `model.joblib`, mã train, tham số, báo cáo, train/validation/test predictions trong `model-artifacts/farmer-v13/` |
| Sáu model sự cố | Sáu joblib của lần benchmark 13/09, báo cáo và các dòng dự đoán validation/test; model giữ trạng thái thí nghiệm |
| Nguồn làm lại thí nghiệm | Bộ mô phỏng có nhãn 42 ngày, CSV lịch sử đã làm sạch, `features_with_split.csv` có mã khách/khu/tủ, báo cáo làm sạch và hash |
| Tài liệu | Giữ các báo cáo cũ để truy vết; lấy `docs/farmer-v13/` làm báo cáo hiện hành |

## Phần để lại trong dự án gốc

- Các snapshot raw theo khách chứa lịch sử chồng lặp, chiếm hơn 5 GB.
- Model đời cũ, bộ dữ liệu trung gian trùng lặp, log dự đoán train lớn của benchmark.
- Bốn model hồi quy benchmark cũ dung lượng lớn; bản này giữ bốn model cải tiến V13 và sáu model sự cố. Báo cáo lịch sử vẫn giữ nguyên nên có thể nhắc tới model không được đóng gói.
- `.env`, khóa riêng, cache Python, cache kiểm thử, Git của dự án nguồn và trạng thái thu dữ liệu vận hành.
- PostgreSQL/Docker volumes không nằm trong thư mục nguồn nên không có trong ZIP. Clone mới không mang sẵn cơ sở dữ liệu đang chạy của máy cũ.

`GITHUB_PACKAGE_MANIFEST.json` liệt kê từng tệp được giữ/bỏ, kích thước và SHA256 của tệp sao chép. Báo cáo train gốc giữ nguyên byte và có thể chứa đường dẫn tuyệt đối trên máy cũ; không sửa chúng để tạo cảm giác dữ liệu đầy đủ hơn thực tế.

## Chạy từ bản GitHub

1. Clone repository hoặc giải nén ZIP, vào thư mục có `docker-compose.yml`.
2. Mở Docker Desktop, chờ Engine running.
3. Trong CMD chạy `scripts\start_v11.cmd`. Script tự tạo `.env` cục bộ với mật khẩu mới, build dịch vụ, nạp dữ liệu/cấu hình demo và chạy bộ kiểm thử. Để xem mật khẩu tài khoản demo trên máy của bạn, chạy `scripts\setup_v10_env.cmd --show-demo-passwords`; không đưa đầu ra chứa mật khẩu lên GitHub.
4. Mở `http://127.0.0.1:18080`. Đọc `README.md` và `docs/farmer-v13/BAO-CAO-NONG-DAN-V13.html`.

Không chạy đồng thời hai bản Compose trên cùng cổng. Script setup hiện dùng tên project/volume cố định của V10; trên máy đã có bản cũ cần quản lý volume/mật khẩu tương ứng, không xóa volume để giải quyết lỗi đăng nhập.

## Tái lập huấn luyện trên dữ liệu đã đóng gói

Cài Python 3.12 và `services/ai-analytics-service/requirements.txt`. Từ gốc repository:

```cmd
python scripts\retrain_github_forecasts.py
python -m nextfarm_device.benchmark_training --project . --source model-artifacts/data/device-v11-validation-b-20260910
```

Lệnh đầu xác minh SHA256 của CSV đặc trưng, tạo bản metadata có đường dẫn phù hợp máy clone tại `github-local-inputs/`, rồi train thật bốn forecast. Báo cáo gốc không bị chỉnh. Kết quả mới nằm ở `model-artifacts/github-retrains/`. Lệnh sau train lại benchmark có nhãn đã đóng gói; đây vẫn là dữ liệu mô phỏng.

Không thể chạy lại **toàn bộ công đoạn làm sạch raw 3 khách** chỉ từ gói này: phải lấy các raw snapshot được ghi trong manifest từ bản gốc trước. Bản này đủ xem kết quả làm sạch và tái train từ CSV đã làm sạch, không nhận là đã chứa toàn bộ raw.

`model-artifacts/problem-b/` sẽ sinh trạng thái thu mới khi ứng dụng chạy. Thu dữ liệu mới đủ hợp đồng 72 giờ và train vận hành khác với tái lập thí nghiệm lịch sử. Model trong gói chưa được nghiệm thu thực địa, không đổi thành READY chỉ vì được đưa lên GitHub.

## Đưa lên GitHub

Trong thư mục đích đã có `.git` từ trước. Quá trình đóng gói giữ nguyên Git, không commit/push. Các tệp cũ đang bị đánh dấu Deleted từ trước vẫn giữ nguyên trạng thái đó.

1. Mở GitHub Desktop, chọn repository `NextFarm_Support_AI` và kiểm tra danh sách Changes.
2. Bản dự án mới nằm ngay thư mục gốc (không cần thêm thư mục lồng). Chỉ chọn phần thay đổi bạn muốn đưa lên.
3. Commit rồi Push/Publish từ GitHub Desktop.
4. ZIP trong `dist/` chỉ dùng gửi/chuyển máy; `.gitignore` loại ZIP, `.env` và các lần train/snapshot mới khỏi commit tự động. Đưa mã nguồn đã giải nén lên Git để xem diff và chạy được.

GitHub chặn file Git thường lớn hơn 100 MiB; upload bằng web giới hạn 25 MiB mỗi file. Gói đã được kiểm tra kích thước từng tệp. Dữ liệu lớn đầy đủ nên lưu riêng hoặc dùng Git LFS khi thực sự cần quản lý trong repository: https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github

Không thay đổi chỉ số báo cáo: 243 kiểm thử qua là kết quả fixture/code, không phải độ chính xác ngoài thực địa; 95,59% là trong dung sai đề xuất trên tập lịch sử đã được sử dụng, không phải cam kết mọi câu/dự báo đều đúng.
