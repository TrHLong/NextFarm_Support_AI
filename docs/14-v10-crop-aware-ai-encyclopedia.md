# V10 — Crop-aware AI Encyclopedia Architecture

## 1. Mục tiêu

V10 tách ba khái niệm vốn dễ bị trộn lẫn:

1. **Customer/Farm data** — ai được xem vườn nào.
2. **Crop identity** — vườn/khu đang trồng nông sản gì.
3. **AI capability** — bài toán nào có thể chạy với dữ liệu và domain hiện có.

Do đó 10.000 khách hàng không đồng nghĩa 100.000 file model.

```text
Identity/IAM
   ↓ allowed farm_ids
Farm + Zone profile
   ↓ crop_name
Crop Router
   ↓ crop_key
AI Encyclopedia
   ↓ capability + required inputs + domain status
Model/Rule/Formula/RAG/CV/Remote Sensing
   ↓ evidence
Truth Guard
   ↓
Chat
```

## 2. Crop Router

`crop_key` là khóa kỹ thuật ổn định, ví dụ `tomato`, `grape`, `apple`, `lychee`, `rice`, `maize`. Tên tiếng Việt/không dấu chỉ là alias.

Router không train model. Nó làm bốn việc:
- lấy farm/zone đúng quyền;
- chuẩn hóa nông sản;
- đọc model registry/capability catalog;
- trả trạng thái `ready`, `experimental` hoặc `blocked` cùng lý do.

Một trained shared model không tự động trở thành READY cho mọi cây. Với crop chưa có validation NextFarm thật, Router hạ trạng thái về EXPERIMENTAL.

## 3. AI Encyclopedia

Catalog hiện có 34 crop keys và 32 capabilities. Capability không đồng nghĩa trained model. Các implementation type:

- `trained_model`
- `formula`
- `rule`
- `remote_sensing`
- `computer_vision`
- `llm_rag`
- `hybrid`

Điều này cho phép mở rộng “bách khoa AI” mà không tạo artifact giả.

## 4. LLM Gateway

LLM là planner/verbalizer ở trên tool layer, không phải nguồn số liệu.

```text
Farmer text
  ↓
LLM plan (structured tool)
  ↓
Tenant/Policy
  ↓
Farm Data / Knowledge / Analytics / Crop Router
  ↓
Evidence
  ↓
LLM verbalize (optional)
  ↓
Truth Guard V10
  ↓
Final answer
```

`LLM_PROVIDER=deterministic` là baseline/offline. `LLM_PROVIDER=openai` bật OpenAI Responses API. Nếu provider lỗi, planner rơi về deterministic thay vì để chatbot chết.

## 5. Truth Guard V10

Guard chạy **sau** verbalizer để LLM không thể thêm claim ngoài evidence sau khi đã kiểm tra. Guard gồm:

- numeric grounding;
- source/citation check;
- confidence gate;
- certainty language guard;
- high-risk/control guard;
- tenant evidence guard;
- freshness/stale guard;
- experimental/blocked model guard.

Nguyên tắc: thiếu evidence → abstain, không đoán.

## 6. Model V2.1

V2.1 vẫn có 10 trained model families kế thừa bài toán V9, nhưng training pipeline thử hai candidate (`RandomForest`, `ExtraTrees`) và chọn bằng validation theo thời gian. Test và Leave-One-Farm-Out chỉ dùng đánh giá/quality gate.

Artifact status phải được đọc từ `report.json`; test score đẹp không đủ để bỏ qua cross-farm failure hoặc thiếu lớp sự cố.

## 7. Dữ liệu thật và dữ liệu demo

V10 không đổi provenance cũ cho đẹp giao diện. Runtime simulator vẫn là `simulated_device_calibrated_v9`. Khi NextFarm cấp sandbox, connector thật mới được ghi `nextfarm_api`/`nextfarm_mqtt` sau auth, mapping tenant và validation payload.
