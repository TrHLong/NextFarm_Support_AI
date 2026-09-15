# NextFarm V10.1.1 acceptance benchmark

`acceptance_260.jsonl` chứa đúng 260 ca theo taxonomy của phản biện:

| Nhóm | Số ca |
| --- | ---: |
| Đọc sensor mới nhất | 30 |
| Trạng thái thiết bị | 20 |
| Lịch sử tưới | 20 |
| Lịch tưới | 20 |
| Thiếu dữ liệu/dữ liệu cũ | 20 |
| Truy cập trái phép chéo farm | 20 |
| Hỏi đáp nông học có nguồn | 50 |
| Không đủ nguồn/chống bịa | 30 |
| Tiếng Việt không dấu, sai chính tả, cách nói địa phương | 30 |
| Hội thoại nhiều lượt và kế thừa ngữ cảnh | 20 |

Các ca vận hành lấy đáp án chuẩn trực tiếp từ 11 bảng Parquet bằng khóa bản ghi,
giá trị, đơn vị và timestamp. Planner và oracle dữ liệu là hai phép kiểm tra riêng.
20 ca hội thoại nhiều lượt yêu cầu kế hoạch kết hợp dữ liệu thời gian thực với
Knowledge; các ca tiếng Việt bổ sung thêm tình huống đa nguồn.

50 ca nông học có `expert_review_status=pending_nextfarm_agronomist`. Bộ kiểm tra
offline chỉ xác nhận cấu trúc nguồn và trạng thái review; không tự coi câu trả lời
AI là ý kiến chuyên gia.

Chạy:

```powershell
python scripts\generate_v10_1_operational_data.py
python scripts\generate_v10_1_benchmark.py
python scripts\run_v10_1_acceptance.py
```

Kết quả offline không thay cho kiểm thử Docker/runtime. Báo cáo JSON luôn ghi rõ
trạng thái Docker và hai cổng nghiệm thu bên ngoài: runtime end-to-end và duyệt
nông học của NextFarm.
