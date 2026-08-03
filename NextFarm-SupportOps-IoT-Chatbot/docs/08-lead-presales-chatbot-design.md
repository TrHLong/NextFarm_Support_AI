# 08. Thiết kế chatbot cho khách mới và pre-sales

## 1. Vấn đề cần bổ sung

Khách chưa chính thức là khách hàng của NextFarm vẫn có giá trị rất lớn. Họ có thể vào chatbot để hỏi:

- NextFarm là gì?
- Tôi có vườn nhỏ thì làm được không?
- Tôi muốn làm vườn vải/rau/nhà màng diện tích 50 m2, 1 ha, 5 ha thì cần gì?
- Tưới tự động, NMC, Fertikit, GIS có khác nhau thế nào?
- Tôi chưa biết bắt đầu từ đâu, NextFarm tư vấn ra sao?

Nếu chatbot chỉ nói "không có dữ liệu vườn" thì mất khách. Với nhóm này, chatbot phải hành xử như một nhân viên tư vấn/sale kỹ thuật: hiểu nhu cầu, giải thích vừa đủ, gợi ý lộ trình, hỏi thêm thông tin, và khi khách có tín hiệu mua hàng thì tạo lead/ticket tư vấn.

## 2. Ba chế độ người dùng

| Chế độ | Người dùng | Quyền dữ liệu | Cách chatbot nên trả lời |
|---|---|---|---|
| Visitor | Chưa nhập thông tin | Không đọc dữ liệu riêng | Trả lời kiến thức chung, hỏi nhu cầu, mời để lại liên hệ |
| Lead | Đã nhập tên/số điện thoại nhưng chưa là khách hàng | Không đọc dữ liệu vườn riêng | Tư vấn theo nhu cầu, lưu hồ sơ cơ hội, gợi ý module NextFarm, tạo ticket tư vấn khi cần |
| Customer | Đã xác minh trong DB | Đọc dữ liệu farm được phân quyền | Trả lời dữ liệu vườn, cảnh báo, điều khiển an toàn, ticket kỹ thuật |

## 3. Chatbot pre-sales cần thông minh ở đâu

### 3.1 Hiểu nhu cầu chưa rõ ràng

Ví dụ: "Tôi muốn xây dựng một vườn vải 50 m2".

Chatbot không nên vội bán thiết bị. Nó cần nhận ra các khả năng:

- Nếu là vải thiều/cây ăn quả: 50 m2 là quy mô rất nhỏ, có thể chỉ trồng thử nghiệm vài cây.
- Nếu người dùng nói "vải" theo nghĩa vật liệu/vườn trải vải phủ: cần hỏi lại.
- Nếu khách chưa rõ kỹ thuật: chatbot nên hỏi cây trồng, khu vực, nguồn nước, có nhà màng không, mục tiêu là tự dùng hay kinh doanh.

### 3.2 Tư vấn theo hệ sinh thái NextFarm

Chatbot phải kéo câu trả lời về các nền tảng của công ty một cách tự nhiên:

- GIS: nếu cần quản lý lô/khu/diện tích.
- Tưới thông minh: nếu khách cần giảm công tưới, kiểm soát nước.
- NMC/Weather: nếu cần theo dõi vi khí hậu/thời tiết.
- Fertikit: nếu có nhu cầu châm phân/dinh dưỡng tự động.
- Management: nếu cần nhật ký canh tác, VietGAP, quản lý công việc.
- QR Check: nếu có bán hàng và cần truy xuất nguồn gốc.
- Yield: nếu có sản xuất thương mại và cần dự báo sản lượng.
- AI sâu bệnh: nếu khách cần hỗ trợ nhận diện bệnh qua ảnh.

### 3.3 Biết chốt bước tiếp theo

Câu trả lời tốt không kết thúc bằng lý thuyết. Nó phải đưa ra bước tiếp theo:

- Hỏi thêm 3-5 thông tin quan trọng.
- Đề xuất cấu hình tối thiểu/khuyến nghị/nâng cao.
- Nếu khách có tín hiệu mua: tạo lead/opportunity và ticket tư vấn.
- Nếu khách chỉ hỏi chơi: tiếp tục cung cấp tri thức chung.

## 4. Dữ liệu cần lưu cho khách mới

| Nhóm dữ liệu | Ý nghĩa |
|---|---|
| Hồ sơ lead | Tên, số điện thoại, khu vực, kênh vào, ghi chú ban đầu |
| Nhu cầu canh tác | Cây trồng, diện tích, mô hình nhà màng/ngoài trời, nguồn nước, mục tiêu |
| Bài toán khách gặp | Thiếu nhân công tưới, muốn theo dõi từ xa, muốn VietGAP/QR, muốn châm phân, muốn cảnh báo sâu bệnh |
| Mức độ quan tâm | Hỏi thông tin, muốn báo giá, muốn tư vấn viên gọi, muốn demo |
| Module đề xuất | GIS, Tưới, NMC, Fertikit, Management, QR, Yield, Weather, AI sâu bệnh |
| Lịch sử tư vấn | Bot đã tư vấn gì, khách trả lời gì, bước tiếp theo |
| Cơ hội bán hàng | Trạng thái lead, điểm tiềm năng, người phụ trách, hẹn gọi lại |

## 5. Bảng dữ liệu bổ sung

| Bảng | Mục đích |
|---|---|
| `sales.lead_profiles` | Hồ sơ khách tiềm năng đã nhập thông tin |
| `sales.lead_requirements` | Nhu cầu cụ thể: cây, diện tích, khu vực, mục tiêu, hạ tầng hiện có |
| `sales.lead_pain_points` | Vấn đề khách đang gặp: tưới tay, thiếu dữ liệu, sâu bệnh, VietGAP, truy xuất |
| `sales.module_recommendations` | Module NextFarm chatbot đề xuất cho lead |
| `sales.consultation_notes` | Lịch sử bot tư vấn và câu hỏi làm rõ |
| `sales.opportunities` | Cơ hội bán hàng khi khách có tín hiệu mua/demo/ký hợp đồng |
| `sales.proposal_drafts` | Bản đề xuất cấu hình sơ bộ do chatbot tạo |

## 6. Ví dụ trả lời đúng

Khách hỏi: "Tôi muốn xây dựng một vườn vải 50 m2 thì cần thế nào?"

Câu trả lời mong muốn:

> Nếu anh/chị nói vườn vải thiều/cây ăn quả thì 50 m2 là quy mô nhỏ, phù hợp làm thử nghiệm hoặc vườn gia đình. Với diện tích này, chưa cần đầu tư quá nặng. Hướng tối thiểu là chia 1-2 khu tưới, dùng tưới nhỏ giọt hoặc phun mưa cục bộ, có thể thêm cảm biến độ ẩm đất để biết khi nào cần tưới. Nếu mục tiêu là học cách vận hành nông nghiệp số, NextFarm có thể bắt đầu từ Tưới thông minh + nhật ký Management. Nếu sau này mở rộng diện tích, có thể thêm GIS để quản lý lô, NMC/Weather để theo dõi thời tiết, QR Check nếu bán sản phẩm. Anh/chị cho tôi biết thêm: trồng vải thiều hay loại cây khác, ở tỉnh nào, có sẵn nguồn nước/bơm chưa, và muốn làm để gia đình hay kinh doanh?

Điểm hay của câu này:

- Không bịa số liệu.
- Không bán quá mức cho vườn nhỏ.
- Vẫn dẫn về hệ sinh thái NextFarm.
- Hỏi thêm thông tin để tiếp tục tư vấn.
- Có thể lưu lead nếu khách muốn tư vấn viên gọi.

## 7. Mapping vào đề bài chatbot

| Yêu cầu đề bài | Khách mới/pre-sales đóng góp gì |
|---|---|
| Tư vấn nông học & hỗ trợ khách hàng | Trả lời câu hỏi canh tác/giải pháp ngay cả khi chưa có farm_id |
| Chống bịa | Chỉ tư vấn trong phạm vi tri thức, nói rõ khi cần chuyên gia/khảo sát |
| Kho tri thức | Tri thức NextFarm + FAQ + tư vấn triển khai được lưu approved |
| Ticket | Lead có ý định mua/demo được chuyển thành ticket tư vấn |
| Ngôn ngữ đời thường | Câu trả lời phải giống người tư vấn, không giống API/debug |
| Chi phí/hạ tầng | Lead data giúp ước lượng tải hội thoại và tỷ lệ chuyển đổi |

## 8. Tiêu chí đạt cho chatbot pre-sales

- Khách mới hỏi tối thiểu 20 câu phổ biến vẫn nhận câu trả lời có ích.
- Chatbot biết hỏi lại khi nhu cầu mơ hồ.
- Chatbot biết đề xuất module NextFarm phù hợp, không nhồi tất cả module vào mọi câu.
- Khi khách có tín hiệu muốn demo/báo giá/gặp người thật, chatbot tạo opportunity/ticket.
- Không đọc hoặc giả vờ có dữ liệu vườn riêng của khách chưa xác minh.
