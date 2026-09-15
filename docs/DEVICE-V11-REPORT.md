> **BÁO CÁO LỊCH SỬ V11.** Kết quả dưới đây thuộc thí nghiệm mô phỏng cũ. Xem [báo cáo bài toán B hiện hành](problem-b/BAO-CAO-BAI-TOAN-B.html). Không dùng các chỉ số READY dưới đây làm kết quả CSV vận hành 72 giờ hoặc nghiệm thu thực địa.

# Báo cáo kiểm chứng NextFarm phiên bản thiết bị

Báo cáo giúp người thực hiện giải thích bản sửa với giảng viên: dữ liệu ở đâu, bot hiểu câu hỏi bằng cách nào, model học và được đo ra sao, và phần nào chưa đạt yêu cầu. Các số liệu dưới đây lấy trực tiếp từ artifact và kiểm thử của phiên bản được nêu.

Kết luận: 10/10 model đạt quality gate trên dữ liệu mô phỏng. Đã đạt mốc 10/10 READY trong phạm vi thí nghiệm này; chưa có kiểm định thực địa. 32 năng lực hỗ trợ đã được triển khai bằng truy vấn, quy tắc và kiểm tra dữ liệu; đây không phải 32 model được huấn luyện.

| Nội dung yêu cầu | Kết quả hiện tại |
| --- | --- |
| Bỏ ticket và kỹ thuật viên trực chat | Đã sửa giao diện, API trả 410 cho ticket; kỹ thuật viên bị chặn chat, được xem dữ liệu theo quyền và duyệt Knowledge. |
| Mỗi cuộc chat gắn một tủ | Bắt buộc device_id; xác thực tài khoản và farm trước khi đọc dữ liệu. |
| Hai tình huống mất dữ liệu | Mất nguồn và mất MQTT được tách theo giám sát độc lập. Thiếu bằng chứng trả chưa xác định. |
| Kiểm thử bản mới | 50/50 ca API; 21/21 kiểm tra logic. Đây là tỷ lệ ca kiểm thử đạt, không phải độ chính xác AI. |
| 10 model chính | 10 READY mô phỏng, 0 EXPERIMENTAL; chỉ artifact đủ điều kiện được gọi. |
| Tri thức công ty | 18 mục được nhập dạng bản nháp, chờ kỹ thuật viên duyệt. Chưa duyệt thì chatbot chưa dùng. |
| Chạy và build | Bản chạy thử cục bộ ở 19080 đã kiểm tra. Chưa xác nhận build Docker vì phiên làm việc bị từ chối quyền truy cập Docker Engine. |

Thư mục dự án: D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1

Phiên bản dữ liệu và model: device-20260910T012458Z-3f9c7ab697

## Luồng câu hỏi và phân quyền

Luồng đang chạy dùng bộ định tuyến quy tắc tiếng Việt, API đọc dữ liệu và mẫu diễn giải có bằng chứng. Không gọi ChatGPT, OpenAI hay Gemini; không có MCP server trong luồng này. Model ML dự báo được gọi ở nhánh dự báo, không nhận trực tiếp câu hỏi văn bản.

| Bước | Xử lý thật | Dấu vết kiểm chứng |
| --- | --- | --- |
| 1 | Đăng nhập nhận token; chọn một tủ thuộc danh sách được cấp quyền. | POST /auth/login; GET /devices |
| 2 | Chuẩn hóa dấu tiếng Việt, nhận chỉ số, ý định và khoảng thời gian; câu ghép có thể gọi nhiều công cụ. | answers.py → route; trace.plan |
| 3 | Farm API kiểm tra lại tài khoản và device_id, trả dữ liệu kèm customer_id và thời điểm. | store.authorize_device; device_db.read_audits |
| 4 | Hỏi hiện tại: tính từ dữ liệu. Hỏi tương lai: chọn đúng model; thiếu điều kiện thì từ chối dự báo. | api.chat_app; api.analytics_app |
| 5 | Kiểm tra độ mới, nguồn và chất lượng; dựng câu trả lời, lưu nguồn số liệu và công cụ đã gọi. | device_db.chat_log.trace |
| 6 | Phản hồi hữu ích/chưa đúng được lưu để rà soát; không tự biến lời khách hàng thành nhãn train. | device_db.chat_feedback; training_use_allowed=false |

### Ví dụ có thể trình bày

“Độ ẩm 62% có cao không?”: bot đọc số đo thật của tủ, tách 62% là số khách hàng nhập chưa xác minh, rồi so với ngưỡng cấu hình. Ngưỡng hiện tại là cấu hình demo, chưa phải tiêu chuẩn nông học cho mọi cây trồng.

“Dự báo độ ẩm đất sau 30 phút”: chỉ gọi model độ ẩm đất nếu dữ liệu mới và hợp lệ. “Dự báo độ ẩm không khí”: hiện không có model tương ứng nên phải nói chưa phát hành dự báo, không lấy model khác thay thế. “Giá vàng ngày mai” là ngoài phạm vi, không được nhận từ vàng thành van.

“Tủ không gửi dữ liệu nữa”: giám sát độc lập mới xác nhận có mất nguồn hay vẫn có nguồn nhưng MQTT lỗi. Khi chỉ thấy trạng thái cũ, bot nói chưa đủ bằng chứng. Giám sát độc lập trong demo là mô phỏng tại server; hệ thống thật cần kênh nguồn độc lập tương ứng.

Cơ chế quy tắc chưa chứng minh hiểu mọi cách diễn đạt. Câu chưa khớp công cụ hoặc tri thức đã duyệt sẽ yêu cầu bổ sung thông tin; không dùng LLM tự viết số liệu.

## Dữ liệu nguồn và phạm vi mô phỏng

| Nhóm | Nhịp trong bản mới | Cách sử dụng |
| --- | --- | --- |
| Số đo cảm biến | Gửi 60 giây; lưu một mẫu mỗi 10 phút | Số đo hiện tại, lịch sử và đặc trưng model. |
| Trạng thái tủ | MQTT mỗi 5 giây khi có nguồn và mạng | Bơm/van/phân và độ mới trạng thái. CSV thí nghiệm lấy mẫu 10 phút, không đếm như toàn bộ gói MQTT. |
| Lịch tưới | Theo cấu hình | Lịch tại bo; mất MQTT có thể vẫn chạy. |
| Lịch sử tưới | Theo sự kiện kết thúc/gián đoạn | Tổng lượng đo hợp lệ, thời lượng và kết quả; counter reset không được coi là 0. |
| Nhật ký lệnh | Theo sự kiện | Người ra lệnh, thời gian, kết quả xác nhận. Lệnh gửi không chứng minh relay đã chạy. |
| Cảnh báo | Khi chuyển trạng thái | Nguồn, MQTT hoặc thiếu bằng chứng. |
| Hồ sơ khách hàng và tủ | Theo cấu hình | Quyền dữ liệu, ánh xạ ngõ ra, cảm biến và ngưỡng demo. |

Tài liệu gốc: docs/references/Chat-thiet-bi-NextFarm-v0.1.html. Phần cứng, kiểu dữ liệu và liên động dựa theo đặc tả. Biên độ dao động, nhiễu, tần suất sự cố và độ mạnh dấu hiệu báo trước là giả định mô phỏng, chưa hiệu chỉnh bằng đo thực tế.

Điện áp, áp suất, dòng bơm, số lỗi bus và packet loss là các trường bổ sung để nghiên cứu. Chưa xác nhận tất cả tủ thực của công ty có đủ thiết bị đo và API cho các trường này. Mất điện đột ngột không có dấu hiệu báo trước vẫn có thể không dự báo được.

| Bộ thí nghiệm | Số liệu |
| --- | --- |
| Khách hàng mô phỏng / thật | 12 / 0 |
| Thời gian / mốc thời gian | 42 ngày / 6,048 mốc |
| Số dòng đặc trưng | 68,371 |
| Sensor / status CSV | 68,371 / 68,371 |
| Ground truth / sự kiện | 72,576 / 2,284 |
| Lịch sử tưới / lệnh | 2,016 / 2,016 |

68 nghìn dòng không đồng nghĩa 68 nghìn quan sát độc lập: dữ liệu có tự tương quan và chỉ có 12 chuỗi khách hàng mô phỏng. Dữ liệu demo đang chạy của ba tài khoản được lưu riêng, không đổi tên thành 12 khách hàng thật.

## Quy trình từ CSV đến artifact

CSV đầu vào: D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1\model-artifacts\data\device-v11-validation-b-20260910

Mỗi thư mục customers/synthetic_customer_XXX chứa sensor_readings.csv, device_status.csv, incident_ground_truth.csv cùng lịch sử tưới, lệnh, sự kiện và hồ sơ. customer_id và device_id dùng đối chiếu, không đưa vào đặc trưng học.

| Công đoạn | Cách thực hiện |
| --- | --- |
| Xác minh nguồn | Kiểm tra SHA256 trong manifest.json; không ghi đè bộ dữ liệu cũ khi --generate. |
| Lọc và làm sạch | Chuẩn hóa UTC, sắp thời gian, loại trùng timestamp, chuyển kiểu số. Số đo bad/suspect và dữ liệu thiếu giữ NaN; không giả định mất kết nối hoặc packet loss bằng 0. |
| Tạo đặc trưng | Số đo hiện tại, lag 1/3/6 điểm, trung bình 3 điểm, tốc độ thay đổi theo phút, cờ thiếu. Ghép trạng thái chỉ lùi tối đa 30 giây. Regression chỉ dùng chuỗi của chính chỉ số và cần số đo hiện tại hợp lệ. |
| Tạo target | Regression: giá trị sau 30 phút, khớp thời gian ±60 giây. Classification: có sự cố khởi phát trong 60 phút tiếp theo; loại dòng đang trong chính sự cố đó. |
| Chia dữ liệu | 9 khách hàng phát triển: train 70% đầu và validation 15% tiếp. Test là 15% cuối của 3 khách hàng hoàn toàn chưa học. Purge theo thời điểm kết thúc nhãn. |
| Fit và chọn model | Imputer và bộ lọc đặc trưng chỉ fit trên train. Chọn ứng viên bằng validation. Không refit hoặc hiệu chỉnh xác suất sau test. |
| Đo và xuất | So với baseline, kiểm tra từng khách hàng giữ lại. Lưu dự đoán CSV, số liệu theo khách, confusion matrix, hash model và code train. READY mới vào active_models.json. |

| Phân vùng trước lọc target | Số dòng |
| --- | --- |
| train | 35,847 |
| excluded_or_purged | 22,303 |
| validation | 7,651 |
| test_unseen_customer | 2,570 |

Test đã được dùng cho báo cáo chất lượng và quyết định phát hành, nên đây là test của thí nghiệm đã công bố. Nếu tiếp tục chọn thiết kế theo kết quả này, cần khóa một bộ test mới trước lần khẳng định tiếp theo; không train lại nhiều lần để chọn bảng đẹp nhất.

## Bốn model dự báo số đo

| Model | MAE macro | Baseline tốt nhất | Cải thiện MAE | Trạng thái |
| --- | --- | --- | --- | --- |
| Độ ẩm đất | 0.1837 | 0.3801 | +51.66% | READY |
| Nhiệt độ | 0.1328 | 0.2612 | +49.17% | READY |
| EC | 0.0068 | 0.0121 | +43.41% | READY |
| pH | 0.0058 | 0.0118 | +50.68% | READY |

MAE là sai số tuyệt đối trung bình, cùng đơn vị với chỉ số: độ ẩm tính theo điểm phần trăm, nhiệt độ °C, EC mS/cm, pH theo đơn vị pH. MAE càng thấp càng tốt. Không đổi R² thành “phần trăm chính xác”. Macro ở đây là trung bình MAE của ba khách hàng test, để mỗi khách có trọng số bằng nhau.

Baseline gồm giữ nguyên số đo cuối, trung bình trượt 3 điểm và ngoại suy tuyến tính. Gate đã đặt trước: cải thiện MAE macro tối thiểu 3% so với baseline tốt nhất và tốt hơn baseline ở từng khách hàng test.

### Độ ẩm đất

Train 33,086, validation 7,075, test 2,356 dòng có target. Thuật toán được chọn: extra_trees. Đạt cả điều kiện trung bình và từng khách hàng trong mô phỏng.

### Nhiệt độ

Train 33,086, validation 7,075, test 2,356 dòng có target. Thuật toán được chọn: extra_trees. Đạt cả điều kiện trung bình và từng khách hàng trong mô phỏng.

### EC

Train 32,358, validation 6,861, test 2,310 dòng có target. Thuật toán được chọn: extra_trees. Đạt cả điều kiện trung bình và từng khách hàng trong mô phỏng.

### pH

Train 33,086, validation 7,075, test 2,356 dòng có target. Thuật toán được chọn: extra_trees. Đạt cả điều kiện trung bình và từng khách hàng trong mô phỏng.

| Khách test | Độ ẩm MAE | Nhiệt độ MAE | EC MAE | pH MAE |
| --- | --- | --- | --- | --- |
| synthetic_customer_009 | 0.1890 | 0.1611 | 0.0082 | 0.0056 |
| synthetic_customer_010 | 0.1770 | 0.1190 | 0.0061 | 0.0055 |
| synthetic_customer_011 | 0.1852 | 0.1183 | 0.0062 | 0.0063 |

Thí nghiệm trước chỉ đạt 6/10. Lần này giữ nguyên gate, bổ sung Ridge tự hồi quy cạnh Extra Trees và HistGradientBoosting, dùng đặc trưng của chính chỉ số, và chỉ chấm trường hợp đầu vào hiện tại hợp lệ giống điều kiện inference. Các ứng viên được chọn bằng validation; seed 20260911 được ghi trước khi mở bộ test mới. Cải thiện giữa hai lần không phải nghiên cứu ablation vì cả thiết kế và bộ mô phỏng đã đổi; cần thí nghiệm đối chứng nếu muốn quy kết mức tăng cho riêng từng thay đổi. Các kết quả kém trước đó vẫn được giữ.

## Sáu model dự báo sự cố

| Model | F1 macro theo khách | F1 baseline | Chênh lệch | Trạng thái |
| --- | --- | --- | --- | --- |
| Mất lưu lượng | 0.9533 | 0.9229 | +0.0305 | READY |
| Rò rỉ | 0.9160 | 0.5986 | +0.3174 | READY |
| Ca tưới gián đoạn | 0.9794 | 0.9536 | +0.0259 | READY |
| Sự cố cảm biến | 0.9635 | 0.8875 | +0.0759 | READY |
| Mất nguồn | 0.9769 | 0.9096 | +0.0674 | READY |
| Mất MQTT | 0.9736 | 0.9178 | +0.0558 | READY |

F1 kết hợp precision và recall. Mỗi khách được tính F1 macro trên hai lớp có/không có sự cố; sau đó lấy trung bình ba khách. Accuracy pooled và confusion matrix vẫn được lưu trong JSON, nhưng không dùng accuracy đơn lẻ để che lớp rủi ro ít xuất hiện.

Gate: F1 macro ≥0,65; tăng ≥0,02 so với baseline tốt nhất; mỗi khách test F1 ≥0,55 và recall lớp sự cố ≥0,50. Trước train cần tối thiểu 50 mẫu mỗi lớp trong train, 10 trong validation và 5 trong từng khách test. Baseline gồm lớp đa số và rule ngưỡng hiện tại.

| Model | Train | Validation | Test | Recall rủi ro thấp nhất |
| --- | --- | --- | --- | --- |
| Mất lưu lượng | 34761 | 7434 | 2488 | 0.9000 |
| Rò rỉ | 34799 | 7460 | 2479 | 0.7000 |
| Ca tưới gián đoạn | 34792 | 7422 | 2461 | 0.9333 |
| Sự cố cảm biến | 34783 | 7430 | 2478 | 0.8611 |
| Mất nguồn | 35847 | 7651 | 2552 | 0.9643 |
| Mất MQTT | 35847 | 7651 | 2552 | 0.9286 |

Đã bổ sung tốc độ biến đổi tín hiệu và hai ứng viên HistGradientBoosting có nhiều lá hơn, có/không cân bằng lớp; chọn bằng validation. Ca tưới gián đoạn ở lần này hơn baseline 0.0259. Việc đạt phải đồng thời thỏa mức tăng và từng khách, không dựa vào một F1 cao riêng lẻ.

Các model sự cố READY chỉ chứng minh khớp các dấu hiệu báo trước đã mô phỏng. Nhãn ẩn độc lập với ngưỡng feature tại cùng thời điểm giúp tránh học lại rule, nhưng vẫn không thay thế nhật ký sự cố thực địa do người có chuyên môn xác nhận.

## Ba mươi hai năng lực hỗ trợ phần một

Danh sách này tách khỏi 10 model học máy. Năng lực là một thao tác truy vấn, tính toán hoặc kiểm tra có thể tái sử dụng trong câu trả lời; nhiều năng lực dùng chung một công cụ. Không báo “accuracy” cho phép cộng hay kiểm tra quyền. READY trong catalog là có công cụ và nhóm dữ liệu; không bảo đảm có dữ liệu mới ở mọi thời điểm.

| STT | Năng lực | Nhóm bằng chứng |
| --- | --- | --- |
| 1 | Số đo mới nhất | Số đo cảm biến |
| 2 | Chuỗi số đo theo thời gian | Số đo cảm biến |
| 3 | Giá trị cao nhất và thấp nhất | Số đo cảm biến |
| 4 | Thay đổi số đo đầu và cuối kỳ | Số đo cảm biến |
| 5 | Độ mới dữ liệu | Số đo cảm biến |
| 6 | Chất lượng cảm biến | Số đo cảm biến |
| 7 | So sánh ngưỡng đã cấu hình | Số đo cảm biến |
| 8 | Kết nối tủ hiện tại | Trạng thái tủ |
| 9 | Bằng chứng mất nguồn | Giám sát độc lập |
| 10 | Bằng chứng gián đoạn MQTT | Giám sát độc lập |
| 11 | Trạng thái bơm | Trạng thái tủ |
| 12 | Trạng thái van | Trạng thái tủ |
| 13 | Lý do khóa bơm phân | Trạng thái tủ |
| 14 | Vai trò từng ngõ ra | Hồ sơ tủ |
| 15 | Lịch tưới đang cấu hình | Lịch tưới |
| 16 | Các ca tưới đã chạy | Lịch sử tưới |

Khi giám sát độc lập vắng hoặc đã cũ, khả năng chẩn đoán nguyên nhân mất kết nối phải trả chưa xác định. Kết quả kiểm thử hai lỗi nguồn/MQTT được lưu trong acceptance.json cùng nội dung câu trả lời.

## Ba mươi hai năng lực hỗ trợ phần hai

| STT | Năng lực | Nhóm bằng chứng |
| --- | --- | --- |
| 17 | Tổng nước theo kỳ | Lịch sử tưới |
| 18 | Tổng phân theo kênh | Lịch sử tưới |
| 19 | So sánh hai kỳ tưới | Lịch sử tưới |
| 20 | Ai gửi lệnh và kết quả | Nhật ký lệnh |
| 21 | Cảnh báo theo bằng chứng | Cảnh báo |
| 22 | Thông tin tủ và cảm biến lắp đặt | Hồ sơ tủ |
| 23 | Đếm lệnh báo lỗi trong kỳ | Nhật ký lệnh |
| 24 | Chỉ ra các chỉ số đang thiếu | Số đo cảm biến |
| 25 | Mốc giờ và độ trễ trạng thái | Trạng thái tủ |
| 26 | Loại số đếm thiếu hoặc reset khỏi tổng | Lịch sử tưới |
| 27 | Thời lượng ca có đủ mốc giờ | Lịch sử tưới |
| 28 | Thống kê kết quả ca tưới | Lịch sử tưới |
| 29 | Lọc kỳ lịch theo múi giờ UTC cộng 7 | Hồ sơ tủ |
| 30 | Xuất CSV có mã khách hàng và tủ | Hồ sơ tủ |
| 31 | Kiểm tra quyền truy cập từng tủ | Hồ sơ tủ |
| 32 | Lưu công cụ và bằng chứng câu trả lời | Hồ sơ tủ |

Các câu hỏi minh họa: “Độ ẩm tuần này cao nhất bao nhiêu?”, “Bơm có chạy không?”, “Vì sao chưa châm phân?”, “Hôm nay tưới mấy lần, bao nhiêu nước?”, “Lệnh nào thất bại?”, “Cảm biến thiếu chỉ số nào?”, “Nguồn câu trả lời và CSV ở đâu?”. Không thực hiện điều khiển bơm hay van từ chat.

Giới hạn: bộ định tuyến còn dựa vào mẫu từ; chưa có benchmark ngôn ngữ diện rộng để tuyên bố hỗ trợ mọi câu hỏi. Các phép tính cho thấy dữ liệu đã ghi nhận, không tự khẳng định sự việc ngoài thực địa khi thiết bị im lặng.

## Tự động cập nhật và mở rộng khách hàng

Không train 10 model riêng cho từng khách hàng. Dữ liệu xuất ra vẫn phân biệt customer_id/device_id, sau đó tạo bộ huấn luyện chung và giữ khách chưa từng học để đánh giá. Suy luận luôn chỉ nhận lịch sử của tủ mà tài khoản có quyền đọc.

| Điều kiện tự động hiện tại | Ngưỡng hoặc hành vi |
| --- | --- |
| Kiểm tra dữ liệu mới | Worker kiểm tra mỗi 300 giây; xuất snapshot khi tổng có ít nhất 144 sensor mới so với watermark hoặc khởi tạo lần đầu. |
| Từng tủ trước khi train | Ít nhất 2.016 sensor, 2.016 status, 2.016 nhãn sự cố; ít nhất 20 ca tưới và 20 lệnh; khoảng quan sát ≥14 ngày. |
| Độc lập khách hàng | Ít nhất 9 khách hàng; nhiều tủ của cùng khách không làm tăng số khách độc lập. Chọn chuỗi tủ dài nhất mỗi khách, ghi lại lựa chọn. |
| Nguồn và nhãn | Chỉ pool mô phỏng đủ nhãn. Dữ liệu thật bị chặn cho tới khi có hợp đồng nhãn và kiểm định thực địa. |
| Train và phát hành | Dùng lại pipeline và gate đã công bố. Chỉ thay bộ đang chạy khi cả 10 model mới đạt. Nếu ứng viên không đạt, giữ registry cũ và lưu latest_candidate_report.json để giải trình. Ghi registry nguyên tử; suy luận kiểm tra hash. |
| Ba tài khoản demo hiện tại | Chưa đủ số khách/ngày/lớp sự cố để tự train đạt gate. Ghi BLOCKED với lý do, vẫn dùng registry thí nghiệm hợp lệ trong phạm vi mô phỏng. |

Với 500 khách, ý tưởng vẫn là một bộ model chung hoặc một số cohort có chứng cứ, không phải 5.000 model. Mã hiện tại chưa được thử tải 500 khách; truy vấn đếm và xuất dữ liệu hàng loạt cần benchmark, hàng đợi công việc và giới hạn tài nguyên trước khi triển khai ở quy mô đó.

Các ngưỡng số dòng là điều kiện kỹ thuật tối thiểu, không chứng minh đủ chất lượng thống kê. Thiếu lớp sự cố, nhãn không độc lập, phân bố khác hoặc performance kém đều có thể chặn phát hành sau khi đã đủ số dòng.

## Bản đồ file và bằng chứng có thể truy nguyên

Tất cả đường dẫn dưới đây tương đối với thư mục dự án đã nêu ở trang đầu. Bảng kết quả cũ là bằng chứng lịch sử của v10; không dùng thay báo cáo v11 này.

| File hoặc thư mục | Nội dung để kiểm tra |
| --- | --- |
| nextfarm_device/contracts.py | 10 target và 32 năng lực; tên và phạm vi không đánh đồng với nhau. |
| nextfarm_device/simulation.py | Giả định vật lý, seed, nhiễu, tần suất sự cố, nhãn ẩn. |
| nextfarm_device/ml.py | Làm sạch, đặc trưng, tách dữ liệu, train, baseline, gate và inference. |
| nextfarm_device/answers.py và api.py | Nhận ý định, API, điều kiện từ chối, giải thích bằng chứng và ràng buộc tủ. |
| nextfarm_device/store.py và runtime.py | Phân quyền, schema device_db, MQTT và hai tình huống gián đoạn. |
| nextfarm_device/automation.py | Xuất CSV tự động, điều kiện dữ liệu mới, train và registry. |
| apps/device-web và apps/device-data-studio | Giao diện nông dân và dữ liệu; không có luồng tạo ticket. |
| apps/knowledge-studio | Kỹ thuật viên xem và duyệt tài liệu. |
| model-artifacts\data\device-v11-validation-b-20260910 | CSV mới theo khách hàng, manifest và hash; giữ bộ trước đó riêng. |
| model-artifacts/device-v11/latest_training_report.json | Bảng tổng mới nhất: nguồn, split, phương pháp, metrics và lý do gate. |
| model-artifacts/device-v11/runs/device-20260910T012458Z-3f9c7ab697 | training_report.json; model_summary.csv; processed_features_targets.csv; từng *_report.json, *_predictions.csv và .joblib; training_code. |
| model-artifacts/device-v11/active_models.json | Chỉ các model READY và hash artifact để phục vụ dự báo. |
| docs/device-v11/acceptance.json và unit-tests.xml | 50 ca kiểm tra API và 21 kiểm tra logic; không phải benchmark accuracy ML. |
| docs/device-v11/synthetic_backfill_correction.json | Bản ghi trước khi sửa các payload backfill mô phỏng; không sửa dữ liệu NextFarm thật. |

docs/device-v11/export_verification.json xác nhận: tách khách train/test, purge thời gian và nạp lại cả 10 artifact để tái tạo các dự đoán test đã lưu. Mã ứng viên, seed và kết quả từng lần được giữ trong thư mục runs; kết quả không được chọn bằng việc hạ gate.

## Các bước tự kiểm tra và ghi báo cáo

Để xem bản mới đang chạy thử, mở http://127.0.0.1:19080 và dùng tài khoản hiện có. Muốn áp dụng qua Docker, mở CMD trong thư mục dự án và chạy scripts\start_v11.cmd. Script build, nhập bản nháp tri thức và chạy unit tests; nếu báo lỗi thì lưu đầy đủ log. Không coi cổng 18080 đã nâng cấp thành công trước khi bước build này hoàn tất.

| Bước | Thao tác | Kết quả cần ghi |
| --- | --- | --- |
| 1 | Đăng nhập lần lượt nongdan.long, nongdan.lan, nongdan.minh. | Mỗi người chỉ thấy đúng một tủ demo. Chụp tên tủ và customer_id. |
| 2 | Chưa chọn tủ, thử gửi câu hỏi; sau đó chọn tủ. | Chưa chọn thì không gửi; khi chọn xong mọi câu hỏi gắn cùng device_id. |
| 3 | Mở tab Dữ liệu, xem từng nhóm; chọn Tuần này khi Hôm nay ít bản ghi. | Ghi count, thời điểm cuối, nguồn synthetic và ID khách/tủ. |
| 4 | Tải CSV số đo và lịch sử tưới. | Mở file kiểm tra customer_id, device_id; giá trị thiếu không bị tự thay bằng 0. |
| 5 | Hỏi “Độ ẩm 62% có cao không?”. | Số đo cảm biến và 62% khách nhập phải phân biệt; ngưỡng demo được nói rõ. |
| 6 | Hỏi “Dự báo EC” và “Dự báo độ ẩm không khí”. | EC được gọi khi dữ liệu đủ; độ ẩm không khí chưa có model phải từ chối dự báo. |
| 7 | Hỏi bơm, van, lịch tưới, tổng nước, lệnh và cảnh báo. | Ghi câu hỏi, ý định, dữ liệu gốc và câu trả lời. Không thấy yêu cầu tạo ticket. |
| 8 | Hỏi “Giá vàng ngày mai thế nào?” và “Bật bơm ngay”. | Câu ngoài phạm vi không được tạo số liệu; chat không thực hiện lệnh điều khiển. |
| 9 | Đăng nhập kythuat.01, mở trang dữ liệu và Duyệt tri thức. | Đọc khách theo quyền, không trực chat; duyệt tài liệu DEVICE_SPEC_V11 nếu nội dung chính xác. |
| 10 | Mở tab 10 model và 32 năng lực. | Ghi đúng 10 model READY mô phỏng; 32 hỗ trợ là truy vấn/rule, không ghi accuracy cho chúng. |

Mật khẩu dùng trong .env hiện tại; báo cáo không sao chép mật khẩu, token hoặc INTERNAL_SERVICE_KEY. Bằng chứng API trả về luôn phải kiểm tra sau đăng nhập.

## Kiểm tra cảnh báo và những việc còn phải hoàn thành

Có thể tái chạy bộ kiểm thử API sau Docker bằng Python đã cài httpx: python scripts/check_device_acceptance.py --base http://127.0.0.1:18080 --output docs/device-v11/acceptance-docker.json --scenarios. Kịch bản chỉ dùng trong môi trường demo; script đọc khóa nội bộ từ .env và tự trả simulator về trạng thái normal.

| Tình huống | Dữ liệu cần đối chiếu | Câu trả lời mong đợi |
| --- | --- | --- |
| Mất nguồn | Giám sát độc lập power_confirmed=false, thời điểm mới; không có status/sensor mới từ tủ. | Nêu bằng chứng mất nguồn; trạng thái bơm/van cũ không phải hiện tại. |
| MQTT gián đoạn | Giám sát nguồn còn, mqtt_connected=false; lịch địa phương có thể vẫn chạy. | Nêu gián đoạn truyền dữ liệu; không kết luận bơm dừng hoặc ca tưới thất bại chỉ vì mất mạng. |
| Chỉ im lặng | Status cũ, không có giám sát nguồn mới. | Chưa đủ bằng chứng phân biệt mất điện và MQTT. |
| Counter reset hoặc thiếu | volume_valid=false, counter_reset=true hoặc giá trị trống. | Không cộng ca này như 0; tổng hợp lệ được ghi là chưa đầy đủ. |

### Phần chưa đạt cần trình bày thẳng

1. 10/10 model READY của một bộ test mô phỏng không đồng nghĩa độ chính xác ngoài thực địa. Nếu tiếp tục sửa thiết kế sau khi đọc bảng này, phải giữ test mới độc lập cho lần đánh giá khẳng định tiếp theo.

2. Chưa chứng minh hiệu quả NextFarm thực địa. Dữ liệu có 0 khách thật và 0 sự cố được xác nhận ngoài hiện trường. Cần đối chiếu các trường đo bổ sung với phần cứng/API thật và thu nhãn sự cố độc lập.

3. 32 năng lực có code và dữ liệu demo để thực thi, nhưng không phải 32 AI đã học; chưa có benchmark hội thoại lớn. Sự hiểu câu hỏi hiện là quy tắc có giới hạn.

4. Chưa xác nhận build Docker trong phiên này. Không dùng kết quả native_review để ghi “Docker build đã thành công”. Lưu kết quả start_v11.cmd và kiểm thử sau build làm bằng chứng riêng.

5. Chưa thử tải 500 khách, chưa triển khai phân quyền Zalo OA hoặc adapter thiết bị thật. Các cấu hình production cũ không thay thế kiểm định triển khai v11.

Mẫu ghi cho từng ca: thời gian chạy; tài khoản và device_id; câu hỏi; nhóm CSV/API gốc; kết quả mong đợi; kết quả quan sát; ảnh chụp; đạt/chưa đạt; nguyên nhân và file liên quan.
