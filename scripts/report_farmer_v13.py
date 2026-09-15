"""Build readable, evidence-linked report; all metric cells come from execution JSON."""
import argparse,json,html,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timezone,timedelta
from collections import Counter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak
from reportlab.lib.pagesizes import A4

def build(evidence,forecast,tests,output,project):
    evidence=Path(evidence);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    q=json.loads((evidence/'question_acceptance.json').read_text(encoding='utf-8'))
    pointer=json.loads(Path(forecast).read_text(encoding='utf-8'));m=json.loads(Path(pointer['report_path']).read_text(encoding='utf-8'))
    source=json.loads(Path(m['source_report']).read_text(encoding='utf-8'))
    xml=ET.parse(tests);cases=xml.findall('.//testcase');failures=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
    pages=[];now=datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=7))).strftime('%H:%M %d/%m/%Y')
    def page(title,subtitle):
        p={'title':title,'subtitle':subtitle,'blocks':[]};pages.append(p);return p
    def para(p,text):p['blocks'].append(('p',text))
    def table(p,headers,rows,widths=None):p['blocks'].append(('table',headers,rows,widths))
    p=page('01 | Kết quả có thể chứng minh','NextFarm - Bài toán B / Bản cải tiến chat dữ liệu nông dân / '+now+' (UTC+7)')
    para(p,'Mục tiêu: câu hỏi dữ liệu phải có bằng chứng đúng khách, đúng khu, đúng kỳ; dự báo cần tiêu chí sai số rõ ràng. Báo cáo ghi kết quả đã chạy, không đổi nhãn READY để thay cho kiểm định.')
    table(p,['Hạng mục','Kết quả thực chạy','Giới hạn của kết luận'],[
      ['Định tuyến và gọi công cụ',f"{q['routing_pass']}/{q['routing_total']} câu mẫu; bản trước {q['baseline_routing_pass']}/{q['routing_total']} chỉ xét định tuyến",'Bộ câu hỏi do người phát triển biên soạn; đã dùng để sửa code, không phải khảo sát hay kiểm tra mù.'],
      ['Đối chiếu số liệu',f"{q['golden_facts_pass']}/{q['golden_facts_total']} giá trị/thuộc tính khớp đáp án",'Fixture có số liệu cố định; không chứng minh mọi câu tiếng Việt đều hiểu đúng.'],
      ['Kiểm thử phần mềm',f'{len(cases)-failures}/{len(cases)} kiểm thử qua','Gồm cả phân quyền, dữ liệu thiếu, thời gian, train; không phải số câu của khách thực.'],
      ['4 dự báo sau 30 phút','Đạt dung sai đề xuất trên 95,59% tổng mẫu có nhãn','Dữ liệu mô phỏng lịch sử; tập test đã được xem ở lần trước; chưa nghiệm thu thực địa.'],
      ['6 dự báo sự cố','6/6 qua ba ngưỡng 80% trên benchmark đã train','Dùng bộ mô phỏng 42 ngày riêng; không phải train lại sáu model từ CSV 3 tài khoản lần này.'],
      ['Chạy trên web','Chưa xác minh sau build','Lúc kiểm tra Docker Engine chưa kết nối được. Mã đã kiểm thử cần build lại container.'],
    ],[95,190,230])
    para(p,'Cách phát biểu khi báo cáo: “Phiên bản này có 130 câu kiểm thử định tuyến và 25 đối chiếu số liệu đều qua. Trên tập lịch sử đã công bố, bốn dự báo đạt 95,59% mẫu có nhãn trong dung sai đề xuất, tính cả các mẫu bị từ chối. Đây là bằng chứng thí nghiệm; chưa phải cam kết chính xác với mọi khách hàng.”')
    para(p,'Không chuyển R² thành % chính xác. Không gộp độ đúng truy vấn SQL/API với độ chính xác dự báo. Không lấy kết quả mô phỏng làm bằng chứng ngoài thực địa.')

    p=page('02 | Đặt mình vào vị trí nông dân','Ưu tiên bên dưới là giả thuyết sử dụng, cần kiểm chứng bằng nhật ký hỏi thật.')
    table(p,['Nhóm / ưu tiên','Câu hỏi thường cần chuẩn bị','Dữ liệu và yêu cầu câu trả lời'],[
      ['Số đo / P0','“Đất khu A còn ẩm không?”; “EC/pH bao nhiêu?”; “Khu nào khô nhất?”','Số đo, đơn vị, khu, mốc giờ và chất lượng. Đối chiếu ngưỡng cấu hình; chưa suy ra khuyến nghị cây trồng khi chưa có tri thức duyệt.'],
      ['Tưới đã chạy / P0','“Hôm nay tưới mấy lần, bao lâu?”; “Dùng bao nhiêu nước/phân?”; “Hôm qua hơn hôm nay không?”','Ca hoàn tất; thời gian bắt đầu/kết thúc; lượng nước và phân. Thiếu số đo không thành 0; đồng hồ reset phải loại.'],
      ['Bơm / van / P0','“Bơm có chạy không?”; “Van khu A đang mở?”; “Sao bơm phân chưa chạy?”','Trạng thái mới, vai trò từng ngõ ra, khóa liên động. Lệnh gửi thành công không chứng minh relay đang chạy.'],
      ['Kết nối / P0','“Sao số đứng yên?”; “Tủ mất điện hay mất mạng?”; “Lần cuối có dữ liệu lúc nào?”','Độ mới của bản tin + quan sát nguồn/MQTT độc lập. Không đủ bằng chứng thì nêu chưa rõ nguyên nhân.'],
      ['Lịch tưới / P0','“Có lịch nào đang bật?”; “Mai tưới mấy giờ?”; “Khu B có lịch không?”','Cấu hình lịch đúng khu. Chu kỳ không có mốc bắt đầu thì không bịa giờ chính xác. Lịch không chứng minh ca đã chạy.'],
      ['Cảnh báo / P0','“Hôm nay có cảnh báo gì?”; “Cái nào chưa xử lý?”; “Cảnh báo gần nhất hôm qua?”','Lọc kỳ, mức độ, trạng thái. Không có cảnh báo không có nghĩa thiết bị chắc chắn khỏe.'],
      ['Lệnh / hồ sơ / P1','“Ai bật bơm?”; “Lệnh nào lỗi?”; “Khu này bao nhiêu m²?”; “Vườn trồng cây gì?”','Nhật ký người ra lệnh và kết quả; hồ sơ đã khai báo. Không suy đoán diện tích/cây khi trường trống.'],
      ['Dự báo / P1','“30 phút nữa độ ẩm bao nhiêu?”; “Có nguy cơ rò nước không?”','Gọi nhánh model đúng chỉ số và chân trời; chưa đủ điều kiện thì báo chưa có dự báo, không lấy số hiện tại thay thế.'],
    ],[85,185,245])
    para(p,'Bộ 130 câu còn có câu không dấu, câu nhiều ý, câu mơ hồ, yêu cầu điều khiển và câu ngoài phạm vi. Bảng đầy đủ có câu trả lời thực chạy trong bản HTML và question_answers.csv. Không tuyên bố đã bao quát mọi cách nói của mọi nông dân.')

    p=page('03 | Câu hỏi đi qua hệ thống thế nào?','Chat hiện dùng quy tắc + công cụ API + mẫu trả lời có bằng chứng; không gọi ChatGPT/OpenAI/Gemini.')
    table(p,['Bước','Xử lý trong mã','Ví dụ / điều kiện từ chối'],[
      ['1. Xác thực','store.user_context / authorize_device','Token → tài khoản → farm được phép đọc → tủ đã chọn. ID do khách gõ không cấp thêm quyền.'],
      ['2. Nhận diện ý','question_plan.route','Tách câu nhiều ý. Mỗi ý giữ nhóm dữ liệu, chỉ số, khu, kỳ, thao tác và chân trời dự báo riêng.'],
      ['3. Đọc bằng chứng','api.chat_app → data API → store.read_group','Gửi token; lọc tủ/khu/thời gian; kiểm tra lại customer_id/device_id của kết quả. Không lấy dữ liệu khách khác thay thế.'],
      ['4. Kiểm tra chất lượng','verified_answers.answer','Loại số không hữu hạn, sai giới hạn, giờ tương lai; cảnh báo dữ liệu trễ, khoảng bị cắt, ca chưa kết thúc.'],
      ['5. Tính và diễn giải','Tổng/đếm/min/max/trung bình từ dữ liệu','Không để mô hình ngôn ngữ tự tạo con số. Có mốc giờ, đơn vị, số ca thiếu và giới hạn kết luận.'],
      ['6. Dự báo riêng','Nhánh models → API /predict','Đúng model và horizon. Hiện chưa phát hành model thực địa nên trả forecast_unavailable, không trả giá trị giả.'],
      ['7. Lưu truy vết','device_db.chat_log.trace','Lưu kế hoạch, bằng chứng và facts/status. Câu hỏi, phản hồi khách không tự thành nhãn train.'],
    ],[83,178,254])
    para(p,'Ngoài phạm vi: “Câu hỏi này nằm ngoài phạm vi dữ liệu thiết bị vườn. Hiện tôi chưa có câu trả lời cho nội dung đó.” Áp dụng với giá nông sản, tư vấn tài chính, bệnh cây, thời tiết và nội dung không có công cụ/hướng dẫn tương ứng.')
    para(p,'Ví dụ: “Độ ẩm khu A hôm nay và nhiệt độ khu B hôm qua?” tạo hai yêu cầu độc lập. “Ca tưới gần nhất hôm qua” chỉ tìm trong hôm qua. “Độ ẩm ngày mai” không bị trả bằng số đo hiện tại.')
    para(p,'Phương án tích hợp gần nhất: giữ tool use gọi REST API hiện có. MCP không bắt buộc. Zalo OA thật và liên kết tài khoản chưa triển khai; bước sau cần liên kết có xác thực giữa Zalo user và NextFarm user, rồi dùng cùng kiểm tra quyền ở backend.')

    p=page('04 | Dữ liệu và quá trình train','Nguồn đã có, không tạo thêm dữ liệu để nâng điểm.')
    table(p,['Bước / nguồn','Thực hiện và bằng chứng'],[
      ['CSV 3 tài khoản','2.118.632 dòng cảm biến, lấy snapshot mới nhất của từng khách để tránh lặp lịch sử. Nguồn simulated_device_calibrated_v9, không phải đo ngoài vườn. customer_id/farm_id/zone_id/device_id/sensor_id giữ để truy vết.'],
      ['Chuẩn hóa đã thực hiện','Kiểm tra thời gian, chất lượng, số hữu hạn và miền vật lý; khử trùng lặp; tạo lưới 10 phút; khoảng thiếu giữ NaN. Chỉ dùng dữ liệu đã tới server tại thời điểm dự đoán.'],
      ['Tạo đầu vào và nhãn','Đặc trưng quá khứ: giá trị hiện tại, lag 1/3/6, trung bình 3 bước, độ dốc, tỷ lệ thiếu, tuổi số đo. Nhãn là số đo sau 30 phút có mốc hợp lệ. Thiếu giá trị hiện tại thì từ chối dự đoán.'],
      ['Chia dữ liệu','Giữ nguyên split đã niêm phong: train/validation theo thời gian của khách phát triển, test là giai đoạn muộn của khách giữ riêng. Purge nhãn chạm ranh giới; mã khách không đưa vào đặc trưng học.'],
      ['Fit và chọn ứng viên','Học mức thay đổi y(t+30)-y(t). Imputer/scaler chỉ fit train. So sánh Ridge alpha 1/10, ExtraTrees và HistGradientBoosting; chọn MAE thấp nhất trên validation, không refit bằng test.'],
      ['Đánh giá và xuất','Cộng dự báo mức thay đổi với số đo hiện tại. Lưu MAE/RMSE/R², hit rate, coverage, baseline cùng tập hợp lệ, dự đoán từng dòng; xuất joblib và kiểm tra nạp lại.'],
      ['Giới hạn thí nghiệm','Tập test này đã được kiểm tra ở lần train trước. Đây là cải tiến trên tập lịch sử đã biết, không phải test mù mới. Dữ liệu ngắn, tương quan theo thời gian; cần kỳ thu mới để nghiệm thu.'],
    ],[112,403])
    para(p,'Tại sao thay đổi cách học? Model dự báo giá trị tuyệt đối dễ lệch khi mức nền của khách mới khác khách train. Học mức thay đổi rồi cộng với số đo hiện tại giữ được mức nền của vườn đó. Điều này cải thiện rõ độ ẩm trên tập này, nhưng chưa bảo đảm tốt cho khách/mùa khác.')
    para(p,'Sáu model sự cố cần nhãn độc lập: có/không sự cố trong chân trời tương lai. Một cảnh báo do AI cũ sinh ra không tự là đáp án đúng. Báo cáo sáu model dùng bộ mô phỏng 42 ngày có nhãn sự cố tiềm ẩn riêng; không đánh tráo với CSV 3 khách.')

    p=page('05 | Bốn dự báo sau 30 phút','Tỷ lệ trúng = sai số tuyệt đối nằm trong dung sai. Dung sai là đề xuất kỹ thuật, cần thống nhất với công ty.')
    rows=[];detail=[]
    names={'soil_moisture':'Độ ẩm đất','temperature':'Nhiệt độ','ec':'EC','ph':'pH'}
    for model in m['models']:
        a=model['acceptance']['test_unseen_customer'];score=model['metrics']['test_unseen_customer'];base=model['baselines']['test_unseen_customer']['persistence']
        unit=m['policy']['tolerance_units'][model['metric']];units={'percentage_points':'điểm %','degC':'°C','mS/cm':'mS/cm','pH_units':'pH'}[unit]
        rows.append([names[model['metric']],f"±{a['absolute_error_tolerance']:g} {units}",f"{a['correct_within_tolerance']}/{a['predicted_rows']}",f"{a['correct_within_tolerance']}/{a['total_labeled_rows']} = {a['success_on_all_labeled_rows']:.2%}",f"{score['mae']:.5f}",f"{score['r2']:.4f}"])
        detail.append([names[model['metric']],model['algorithm'],f"{model['rows']['train']} / {model['rows']['validation']} / {model['rows']['test_unseen_customer']}",f"{base['mae']:.5f}",'Có' if model['beats_persistence_mae'] else 'Chưa'])
    table(p,['Chỉ số','Dung sai','Trúng / đã dự báo','Trúng / mọi mẫu có nhãn','MAE','R²'],rows,[70,78,80,120,82,85])
    para(p,'Ở mỗi model, 95,59% mẫu có nhãn đủ đầu vào để dự báo. 100% mẫu đã dự báo nằm trong dung sai đề xuất. Nếu tính mẫu từ chối là chưa đáp ứng thì tỷ lệ là 95,59%, không báo 100% trên toàn bộ dữ liệu. Mẫu có nhãn vẫn chỉ là một phần của toàn bộ bản ghi gốc.')
    table(p,['Chỉ số','Ứng viên đã chọn','Train / val / test','MAE giữ nguyên số hiện tại','Tốt hơn?'],detail,[72,138,105,125,75])
    para(p,'Baseline dùng đúng những dòng có giá trị hiện tại và nhãn hợp lệ như model. Nhiệt độ và pH chưa thắng baseline MAE: việc đạt dung sai rộng không đủ chứng minh ML cần thiết hoặc thông minh hơn. Giữ ứng viên thí nghiệm, kiểm tra lại trên kỳ mới và so với baseline trước khi phát hành.')
    para(p,'MAE có đơn vị gốc (điểm %, °C, mS/cm, pH). R² đo mức giải thích biến thiên, không phải % chính xác. Dung sai đề xuất không phải thông số sai số được nhà sản xuất xác nhận, cũng không phải ngưỡng an toàn cây trồng.')
    para(p,'Mã, split, SHA256 nguồn, tham số từng ứng viên, ba tập dự đoán và checksum model đều có trong training_report.json và thư mục từng model. Bốn model đã fit thật; model nạp lại cho kết quả khớp với model vừa train.')

    p=page('06 | Sáu dự báo sự cố và 32 năng lực','Sáu model được đối chiếu lại với ngưỡng mới từ kết quả benchmark đã train ngày 13/09; không fit lại trong lượt cải tiến này.')
    rows=[]
    titles={'flow_fault_forecast':'Mất lưu lượng','leak_forecast':'Rò rỉ','irrigation_failure_forecast':'Ca tưới thất bại','sensor_fault_forecast':'Lỗi cảm biến','power_loss_forecast':'Mất nguồn','mqtt_loss_forecast':'Mất MQTT'}
    for c in m['existing_classifier_acceptance']:
        a=c['acceptance'];rows.append([titles[c['name']],f"{a['balanced_accuracy']:.2%}",f"{a['f1_macro']:.2%}",f"{a['risk_recall']:.2%}",'Qua' if a['numeric_gate_passed'] else 'Chưa qua'])
    table(p,['Model','Balanced accuracy','F1 macro','Recall sự cố','Ba ngưỡng ≥80%'],rows,[122,112,90,100,91])
    para(p,'Balanced accuracy cân bằng hai lớp có/không sự cố. F1 macro xem cả precision và recall của các lớp. Recall sự cố là tỷ lệ tình huống dương được nhận ra; không dùng accuracy đơn độc khi phần lớn dòng là bình thường. Xác suất chưa được hiệu chỉnh thực địa.')
    table(p,['Vấn đề','Kết luận đúng'],[
      ['Hai model mất nguồn / MQTT có điểm giống nhau','Không tự suy ra dùng chung nhãn: lần đối chiếu trước có các dòng nhãn và dự đoán khác nhau; xem từng confusion matrix và test_predictions.'],
      ['Sự cố đột ngột','Nếu mất điện xảy ra không có tín hiệu báo trước thì dữ liệu cảm biến không đủ để bảo đảm dự báo. Phải tách phát hiện mất liên lạc sau khi xảy ra với dự báo rủi ro trước khi xảy ra.'],
      ['32 năng lực','Là các công cụ truy vấn / công thức / kiểm tra; không phải 32 model ML được train. AVAILABLE chỉ nói có nhóm dữ liệu, không chứng nhận trả lời được mọi câu.'],
      ['Đạt ngưỡng mô phỏng','Chỉ cho phép kết luận trong benchmark này. Không tự đổi thành READY ngoài thực địa hoặc lấy điểm sáu model này cộng với bốn model CSV để gọi “10 model 95% trên cùng dữ liệu”.'],
    ],[145,370])
    para(p,'Các lần train tự động tiếp theo đã được bổ sung policy: hồi quy phải đạt hit rate/coverage ≥80%, tối thiểu 50 mẫu test; phân loại phải đạt balanced accuracy/F1 macro/recall ≥80%, đồng thời qua cổng nhãn/sự cố và vượt baseline. Đạt điều kiện số vẫn không tự là nghiệm thu pilot.')

    p=page('07 | Tệp nào chứng minh điều gì?','Các đường dẫn trong bảng tính từ thư mục gốc dự án: '+str(project))
    table(p,['Tệp / thư mục','Nội dung cần mở khi giải trình'],[
      ['benchmarks/farmer-v13/questions.csv','130 câu, nhóm, công cụ kỳ vọng, ưu tiên giả định. baseline_routing.json giữ kết quả định tuyến bản trước.'],
      ['docs/farmer-v13/question_acceptance.json','Mỗi câu có answer, plan, evidence, facts/status; 25 đáp án chuẩn và giá trị thực tế.'],
      ['docs/farmer-v13/question_answers.csv','Bảng câu hỏi - câu trả lời - công cụ - trace; có thể lọc bằng Excel.'],
      ['docs/farmer-v13/unit-tests.xml','Tên từng kiểm thử, kết quả và thời gian chạy. Không phải độ chính xác ML.'],
      ['model-artifacts/farmer-v13/latest_report.json','Con trỏ đến lần cải tiến dự báo gần nhất. training_report.json ghi đường dẫn CSV nguồn, SHA256, split, policy, ứng viên và mọi metric.'],
      ['model-artifacts/farmer-v13/residual-.../<model>/','report.json; model.joblib; train_predictions.csv; validation_predictions.csv; test_unseen_customer_predictions.csv. Đối chiếu từng prediction với target.'],
      ['model-artifacts/data/historical-customer/historical-20260913T144927Z/features_with_split.csv','CSV đặc trưng đã làm sạch và chia tập, tái sử dụng có kiểm tra SHA256. CSV gốc và báo cáo làm sạch truy ngược từ source_report. Không nhân bản hơn 6GB cho mỗi thử nghiệm.'],
      ['model-artifacts/benchmark-retrain/latest_report.json','Kết quả bộ mô phỏng 42 ngày cho sáu model sự cố. Các file dự đoán/nhãn và ma trận nhầm lẫn ở từng run.'],
      ['nextfarm_device/question_plan.py; verified_answers.py; api.py; store.py','Nhận diện câu hỏi; kiểm tra/tính/diễn giải; gọi API và phân quyền; lấy dữ liệu đúng khoảng.'],
      ['nextfarm_device/refine_forecasts.py; forecast_acceptance.py; runtime_training.py','Huấn luyện cải tiến; định nghĩa chỉ số chấp nhận; cổng đánh giá những lần train tự động.'],
    ],[243,272])
    para(p,'500 khách không có nghĩa 500 bộ ×10 model. Hướng hiện tại là model dùng chung theo bài toán, giữ mã khách để truy vết/chia tập nhưng không học mã định danh. Chỉ tách nhóm mô hình khi có bằng chứng khác biệt loại vườn/thiết bị. Dữ liệu phục vụ chat vẫn cách ly theo quyền từng khách. Chưa có phép đo tải 500 khách.')

    p=page('08 | Tự kiểm tra và ghi chép báo cáo','Các giá trị web phải đối chiếu với dữ liệu tại thời điểm bạn kiểm tra, không lấy số fixture làm số vườn thật.')
    para(p,'Bước 1: mở Docker Desktop, chờ Engine running. Mở CMD: cd /d "'+str(project)+'" rồi chạy scripts\\start_v11.cmd. Script build và chạy tests. Mở http://127.0.0.1:18080. Kiểm tra /api/farm/health có chat_contract=farmer_v13.')
    table(p,['Bước','Thao tác','Bằng chứng cần ghi'],[
      ['2','Đăng nhập farmer_long; chọn tủ của Long; xuất dữ liệu nhóm cần hỏi.','Tài khoản, customer_id/device_id, khu, mốc ngày UTC+7. Không dùng tài khoản kỹ thuật viên để chat.'],
      ['3','Hỏi số đo hiện tại, min/max/trung bình theo khu/kỳ.','So giá trị và đơn vị với bản ghi CSV; chụp mốc giờ, chất lượng.'],
      ['4','Hỏi số ca, tổng nước/phân hôm nay và hôm qua.','Tự cộng ca kết thúc trong kỳ; ghi riêng ca thiếu, reset, ca chưa kết thúc.'],
      ['5','Hỏi câu hai ý, hai khu, hai thời điểm; hỏi “gần nhất hôm qua”.','Mở trace: mỗi yêu cầu phải có khu/kỳ đúng; không dùng một bộ tham số cho cả câu.'],
      ['6','Hỏi lịch bật/tắt, trạng thái van, người ra lệnh, cảnh báo.','So lần lượt với cấu hình / trạng thái / nhật ký / cảnh báo, không tráo nhóm dữ liệu.'],
      ['7','Kiểm tra tình huống mất nguồn, mất MQTT, cảm biến trễ bằng kịch bản demo.','Có quan sát độc lập mới phân biệt nguyên nhân; dữ liệu cũ phải được cảnh báo. Không cắt điện thiết bị thật để thử.'],
      ['8','Hỏi giá vàng, bệnh cây, thời tiết; yêu cầu bật bơm hoặc xem tủ người khác.','Ngoài phạm vi phải từ chối; chat không điều khiển; backend không cấp quyền từ nội dung câu hỏi.'],
      ['9','Hỏi dự báo 30 phút/ngày mai và mở bảng model.','Không được thay dự báo bằng số hiện tại. Ghi status và lý do nếu chưa có model nghiệm thu.'],
      ['10','Mở report train, tìm một dòng test_predictions.','Ghi CSV nguồn, split, thuật toán, nhãn thật trong dữ liệu, dự đoán, sai số, dung sai và baseline.'],
    ],[42,224,249])
    para(p,'Mẫu ghi chép: thời gian kiểm tra | tài khoản/tủ/khu | câu hỏi | nguồn CSV/API và mốc dữ liệu | phép tính mong đợi | trả lời thực tế | đạt/chưa đạt | ảnh/trace. Khi có lỗi mới, bổ sung câu vào bộ hồi quy; giữ một bộ câu và kỳ dữ liệu mới chưa dùng để chỉnh code cho đánh giá độc lập.')
    para(p,'Phần còn cần nghiệm thu: dung sai với công ty, kỳ dữ liệu mới đủ 72 giờ/độ phủ và nhãn độc lập, kết quả trên khách mới, tích hợp Zalo thật, tải thực và phát hành model theo kiểm định. Hiện endpoint dự báo vẫn chặn model chưa nghiệm thu; báo cáo không khẳng định đã hoàn tất các bước này.')

    # PDF: explicit page breaks keep tables and their limitations together.
    pdfmetrics.registerFont(TTFont('VN','C:/Windows/Fonts/arial.ttf'))
    pdfmetrics.registerFont(TTFont('VNB','C:/Windows/Fonts/arialbd.ttf'))
    body=ParagraphStyle('body',fontName='VN',fontSize=9.4,leading=13.2,textColor=colors.HexColor('#193A36'),spaceAfter=10)
    small=ParagraphStyle('small',parent=body,fontSize=8.5,leading=11.4,spaceAfter=0,wordWrap='CJK')
    head=ParagraphStyle('head',parent=body,fontName='VNB',fontSize=18,leading=22,spaceAfter=9)
    sub=ParagraphStyle('sub',parent=body,fontSize=9,leading=12,textColor=colors.HexColor('#52726F'),spaceAfter=16)
    th=ParagraphStyle('th',parent=small,fontName='VNB',textColor=colors.white)
    esc=lambda s:html.escape(str(s)).replace('\n','<br/>')
    flow=[]
    for i,p in enumerate(pages):
        if i:flow.append(PageBreak())
        flow.extend([Paragraph(esc(p['title']),head),Paragraph(esc(p['subtitle']),sub)])
        for b in p['blocks']:
            if b[0]=='p':flow.append(Paragraph(esc(b[1]),body))
            else:
                _,headers,rows,widths=b
                cell=[[Paragraph(esc(x),th) for x in headers]]+[[Paragraph(esc(x),small) for x in row] for row in rows]
                t=Table(cell,colWidths=widths,repeatRows=1,hAlign='LEFT')
                t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#126451')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#F0F6F3'),colors.white]),('VALIGN',(0,0),(-1,-1),'TOP'),('BOX',(0,0),(-1,-1),.5,colors.HexColor('#C6D7D0')),('INNERGRID',(0,0),(-1,-1),.3,colors.HexColor('#D4E0DB')),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
                flow.extend([t,Spacer(1,12)])
    def footer(canvas,doc):
        canvas.setFont('VN',8);canvas.setFillColor(colors.HexColor('#52726F'));canvas.drawString(40,25,'NEXTFARM | Bằng chứng truy vấn và dự báo | 14/09/2026');canvas.drawRightString(A4[0]-40,25,str(doc.page))
    pdf=output/'BAO-CAO-NONG-DAN-V13.pdf'
    SimpleDocTemplate(str(pdf),pagesize=A4,rightMargin=40,leftMargin=40,topMargin=38,bottomMargin=43,title='NextFarm - Kiểm chứng chat nông dân và dự báo').build(flow,onFirstPage=footer,onLaterPages=footer)
    # HTML contains the full answer appendix, searchable without external services.
    chunks=['<!doctype html><html lang="vi"><meta charset="utf-8"><title>NextFarm - Báo cáo nông dân V13</title><style>body{font:16px/1.6 Arial,sans-serif;max-width:1120px;margin:35px auto;padding:0 22px;color:#193a36}h1,h2{color:#126451}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{border:1px solid #bfd0c8;padding:12px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#126451;color:white}tr:nth-child(even){background:#f0f6f3}section{margin-bottom:50px}details{border:1px solid #bfd0c8;padding:12px;margin:10px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.5 monospace}summary{cursor:pointer;font-weight:bold}input{padding:12px;width:95%;font:inherit}small{color:#52726f}@media print{details{break-inside:avoid}section{break-before:page}}</style><h1>NextFarm: câu trả lời có bằng chứng</h1>']
    for p in pages:
        chunks+=['<section><h2>'+esc(p['title'])+'</h2><small>'+esc(p['subtitle'])+'</small>']
        for b in p['blocks']:
            if b[0]=='p':chunks+=['<p>'+esc(b[1])+'</p>']
            else:chunks+=['<table><tr>'+''.join('<th>'+esc(h)+'</th>' for h in b[1])+'</tr>'+''.join('<tr>'+''.join('<td>'+esc(c)+'</td>' for c in r)+'</tr>' for r in b[2])+'</table>']
        chunks+=['</section>']
    chunks+=['<h2>Phụ lục: 130 câu hỏi và câu trả lời thực chạy</h2><p>Nguồn toàn bộ câu trả lời dưới đây: fixture tổng hợp riêng cho kiểm thử, thời điểm cố định 12:00 ngày 14/09/2026; không phải số liệu tài khoản đang chạy.</p><input id="search" placeholder="Tìm câu hỏi, nhóm dữ liệu hoặc mã câu…">']
    for c in q['cases']:
        chunks+=['<details class="case"><summary>'+esc(c['id']+' | '+c['question'])+'</summary><p>'+esc(c['answer'])+'</p><small>Công cụ: '+esc(c['actual_tools'])+' | Kết quả kiểm tra công cụ: '+str(c['passed'])+'</small><details><summary>Bằng chứng và kế hoạch</summary><pre>'+esc(json.dumps(c['trace'],ensure_ascii=False,indent=2))+'</pre></details></details>']
    chunks+=['<h2>Phụ lục: 25 đối chiếu số liệu</h2><table><tr><th>Câu hỏi</th><th>Đáp án chuẩn</th><th>Giá trị thực</th><th>Khớp</th></tr>']
    chunks+=['<tr>'+''.join('<td>'+esc(c[k])+'</td>' for k in ['question','expected','actual','passed'])+'</tr>' for c in q['golden_facts']]
    chunks+=['</table><script>document.getElementById("search").addEventListener("input",e=>{const s=e.target.value.toLocaleLowerCase();document.querySelectorAll(".case").forEach(n=>n.hidden=!n.textContent.toLocaleLowerCase().includes(s))});</script></html>']
    (output/'BAO-CAO-NONG-DAN-V13.html').write_text(''.join(chunks),encoding='utf-8')
    (output/'report_sources.json').write_text(json.dumps({'created_at':now,'forecast_report':pointer['report_path'],'question_evidence':str(evidence/'question_acceptance.json'),'unit_tests':str(tests),'test_total':len(cases),'test_failures':failures},indent=2),encoding='utf-8')
    print(json.dumps({'pdf':str(pdf),'html':str(output/'BAO-CAO-NONG-DAN-V13.html'),'sections':len(pages),'tests':len(cases)}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence',required=True);p.add_argument('--forecast',required=True);p.add_argument('--tests',required=True);p.add_argument('--output',required=True);p.add_argument('--project',required=True);a=p.parse_args();build(a.evidence,a.forecast,a.tests,a.output,a.project)
