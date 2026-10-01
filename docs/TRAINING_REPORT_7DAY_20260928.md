# Báo cáo train synthetic 7 ngày — 28/09/2026

## Phạm vi

- Nguồn: `nextfarm_device/simulation.py`
- Thời lượng: 7 ngày liên tục
- Số site synthetic: 12
- Seed: `20260928`
- Tập dữ liệu: `data/device-v11-7day`
- Artifact và metric: `model-artifacts/device-v11-7day`
- Dataset version: `device-20260928T051924Z-2615461321`
- Dữ liệu này chỉ dùng kiểm thử pipeline, không phải telemetry phần cứng NextFarm.

## Số lượng dữ liệu

| Hạng mục | Số lượng |
|---|---:|
| Dòng sau xử lý feature/target | 11.413 |
| Mốc thời gian duy nhất | 1.008 |
| Train | 5.927 |
| Validation | 1.208 |
| Test site chưa thấy | 439 |
| Dòng loại do purge/không thuộc split | 3.839 |
| Tổng model thử nghiệm | 10 |
| Model qua gate synthetic | 4 |
| Model bị chặn | 6 |

## Kết quả model

| Model | Thuật toán | Trạng thái | Test MAE | Test RMSE | Test R² |
|---|---|---|---:|---:|---:|
| `moisture_forecast` | Extra Trees | READY (synthetic) | 0.19050 | 0.24117 | 0.99848 |
| `temperature_forecast` | Extra Trees | READY (synthetic) | 0.13200 | 0.18019 | 0.99739 |
| `ec_forecast` | Extra Trees | READY (synthetic) | 0.00871 | 0.01091 | 0.99916 |
| `ph_forecast` | Extra Trees | READY (synthetic) | 0.00725 | 0.00929 | 0.99484 |

`READY` ở bảng này chỉ có nghĩa là qua quality gate của benchmark synthetic hiện tại. Không được diễn giải thành production-ready.

## Model bị chặn

| Model | Lý do |
|---|---|
| `flow_fault_forecast` | Thiếu độ phủ lớp nhãn trong train |
| `leak_forecast` | Thiếu lớp trong train và site `synthetic_customer_009` |
| `irrigation_failure_forecast` | Thiếu lớp trong train và site `synthetic_customer_009` |
| `sensor_fault_forecast` | Thiếu lớp trong train và site `synthetic_customer_010` |
| `power_loss_forecast` | Thiếu lớp trong train và các site `synthetic_customer_009`, `synthetic_customer_010` |
| `mqtt_loss_forecast` | Thiếu độ phủ lớp nhãn trong train |

## Đánh giá trung thực

Bộ dữ liệu 7 ngày đã làm pipeline train/test chạy được và tạo ra 4 model đạt gate nội bộ. Tuy nhiên, dữ liệu là synthetic, các sự cố và nhãn được sinh theo kịch bản mô phỏng. Vì vậy:

- Không đưa 4 model vào phục vụ nông dân.
- Không ghi “độ chính xác production”.
- Không thay thế rule kiểm tra trực tiếp bằng model.
- Cần dữ liệu vận hành thật, nhiều mùa/vườn và nhãn sự cố được xác nhận trước khi nghiệm thu.

## File bằng chứng

- `data/device-v11-7day/manifest.json`
- `model-artifacts/device-v11-7day/runs/device-20260928T051924Z-2615461321/training_report.json`
- `model-artifacts/device-v11-7day/runs/device-20260928T051924Z-2615461321/model_summary.csv`
- Các file `*_predictions.csv` trong cùng thư mục run.

## Ghi chú cleanup

Do chính sách hệ điều hành của môi trường thực thi, lệnh xóa đệ quy archive cũ bị chặn. Archive `NextFarm-AI-Support-v10.1_ARCHIVE_20260928` chưa được xóa trong lượt này. Bộ 7 ngày được tạo ở thư mục version riêng, không ghi đè dữ liệu cũ.
