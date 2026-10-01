# NextFarm AI Support v10.4 - Simulation Training Evidence

## Thay đổi chính
- Train thật 5 model AI trên dataset mô phỏng 30 ngày, không dùng số liệu kết quả viết tay.
- Tách rõ 5 file train Python theo từng model trong `scripts/model_training_v104/`.
- Mỗi model benchmark 2 thuật toán cây, chọn model bằng Validation; Test chỉ dùng đánh giá cuối.
- Một báo cáo DOCX duy nhất cho toàn bộ vòng đời training và mô phỏng: `docs/BAO_CAO_TRAIN_MODEL_AI_VA_MO_PHONG_HOAN_TAT_V10.4.docx`.
- Báo cáo chứa lý do chọn thuật toán trước phần kết quả, metrics, confusion matrix/ROC/PR hoặc Actual-vs-Predicted/Residual, feature importance và giải thích.
- Artifact đóng gói `.joblib` + `.pkl`, gồm preprocessing pipeline và metadata feature/target.
- Serving mặc định dùng `model-artifacts/simulation-v104/latest/models`.
- Shadow inference, A/B 10%, batch inference và monitoring đã được smoke-test trong cùng run.

## Phạm vi
Toàn bộ số liệu v10.4 là `SYNTHETIC_SIMULATION_ONLY`. Đây là bằng chứng pipeline và thực nghiệm đồ án, không phải xác nhận production ngoài thực địa.
