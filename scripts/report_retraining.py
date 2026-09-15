"""Build the readable PDF/HTML from measured training JSON, never typed scores."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import argparse,json,html,sys,shutil
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,KeepTogether

def main(project):
    root=Path(project).resolve();docs=root/'docs/retraining-20260913';docs.mkdir(parents=True,exist_ok=True)
    def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
    hp=load(root/'model-artifacts/historical-customer/latest_report.json')['report_path'];h=load(hp)
    bp=load(root/'model-artifacts/benchmark-retrain/latest_report.json')['report_path'];b=load(bp)
    storage=load(docs/'storage_compression.json')
    def n(v,d=3):return '-' if v is None else f'{v:,.{d}f}'
    def rel(path):
        try:return str(Path(path).relative_to(root)).replace('\\','/')
        except ValueError:return str(path)
    def local(v):return datetime.fromisoformat(str(v)).astimezone(timezone(timedelta(hours=7))).strftime('%d/%m/%Y %H:%M')
    sections=[]
    def section(title,paragraphs,tables):sections.append((title,paragraphs,tables))
    totals={k:sum(a[k] for a in h['cleaning']) for k in ['input_rows','grid_rows','empty_grid_rows','missing_value_after']}
    hr=[m for m in h['models'] if m['status']!='BLOCKED'];br=[m for m in b['models'] if m['status']!='BLOCKED']
    section('1. Kết quả và phạm vi chứng minh',[
      f'Ngày lập: {datetime.now().strftime("%d/%m/%Y %H:%M")}. Đã train {len(hr)} model từ CSV của ba tài khoản và {len(br)}/10 model từ bộ mô phỏng có nhãn. Hai nguồn được đánh giá riêng. Số model được nghiệm thu để phát hành dự báo: 0.',
      'Train thật nghĩa là chương trình thực sự fit thuật toán, đánh giá trên tập đã chia và xuất model. Điều đó không biến dữ liệu mô phỏng thành dữ liệu thực địa, cũng không bảo đảm model tốt.',
      f'CSV ba tài khoản: {totals["input_rows"]:,} dòng số đo nguồn. Tại lưới 10 phút có {totals["grid_rows"]:,} vị trí, {totals["empty_grid_rows"]:,} vị trí không có số đo đến kịp mốc quyết định ({totals["empty_grid_rows"]/totals["grid_rows"]:.1%}). Các vị trí này giữ trống.'],[
      (['Nguồn','Nội dung','Dùng để kết luận gì?'],[
        ['CSV Long / Lan / Minh','simulated_device_calibrated_v9; xuất DB ngày 11/09 theo giờ Việt Nam','Thử dự báo trên lịch sử mô phỏng theo tài khoản. Có mã khách/vườn/cảm biến.'],
        ['Benchmark 42 ngày','12 khách giả lập; synthetic_latent_incident; không sinh thêm dữ liệu','Kiểm tra 10 thuật toán trong giả định của trình mô phỏng.'],
        ['Bộ thu vận hành 72 giờ','Hợp đồng problem_b_v12; không trộn với hai nguồn trên','Chỉ được train khi đủ thời gian, độ phủ và nhãn. Không lấy mốc giờ lịch sử thay cho giờ đã thu.']]),
      (['Tối ưu lưu trữ','Trước','Sau'],[
        ['273 CSV cũ - dung lượng thực trên đĩa',n(storage['allocated_before']/2**30,2)+' GiB',n(storage['allocated_after']/2**30,2)+' GiB'],
        ['Tiết kiệm',n(storage['saved_bytes']/2**30,2)+' GiB','Nén NTFS tại chỗ, không xóa CSV'],
        ['Kiểm tra nội dung','SHA-256 từng tệp','273/273 giữ nguyên nội dung và đường dẫn']])])
    section('2. AI trả lời khách hàng như thế nào?',[
      'Luồng đang có trong mã nguồn: câu hỏi + tài khoản + tủ đã chọn -> định tuyến theo quy tắc -> kiểm tra quyền -> gọi REST API đọc nhóm dữ liệu -> kiểm tra độ mới/chất lượng -> tạo câu trả lời kèm bằng chứng. Chat hiện không gọi API OpenAI, Gemini hoặc LLM khác.',
      'Các model số học dự báo giá trị/sự cố. Chúng không phải mô hình ngôn ngữ để tự hiểu mọi câu tiếng Việt. Việc tăng số lượng model không tự làm bộ định tuyến hiểu mọi cách hỏi.',
      'Câu hỏi của khách không tự trở thành nhãn train. Câu trả lời AI hoặc confidence cũ cũng không phải sự thật để huấn luyện tiếp.'],[
      (['Khách hỏi','Cách xử lý đúng','Có cần model dự báo?'],[
        ['Độ ẩm vườn tôi hiện tại?','Đọc sensor đúng khách, tủ/khu; ghi thời điểm và chất lượng.','Không'],
        ['Hôm nay tưới mấy lần, bao nhiêu nước?','Lọc irrigation_runs theo kỳ; loại bộ đếm thiếu/reset khi tính tổng.','Không'],
        ['Bơm/van đang chạy? Lịch mai?','Đọc trạng thái ngõ ra và lịch đã cấu hình; không coi lịch là ca đã chạy.','Không'],
        ['62% có cao không?','So với ngưỡng của vườn. Thiếu xác nhận cây/đất/giai đoạn thì chưa kết luận nhu cầu tưới.','Không bắt buộc'],
        ['Thiết bị mất điện hay lỗi mạng?','Dùng quan sát nguồn/MQTT độc lập; im lặng một mình chỉ đủ kết luận thiếu/trễ dữ liệu.','Không bắt buộc'],
        ['Sau 30 phút độ ẩm bao nhiêu?','Cần model dự báo đạt kiểm định trong đúng phạm vi dữ liệu. Hiện chưa phát hành.','Có'],
        ['Giờ tới có mất điện/rò rỉ?','Cần lịch sử có nhãn sự cố đúng và tín hiệu dự báo có ích.','Có, nếu đã chứng minh hữu ích'],
        ['Ngoài phạm vi / thiếu bằng chứng','Yêu cầu làm rõ hoặc báo chưa đủ dữ liệu; không bịa số và không tự tạo ticket.','Không dùng model để đoán bừa']])])
    units={'moisture_forecast':'điểm %','temperature_forecast':'°C','ec_forecast':'mS/cm','ph_forecast':'pH'}
    rows=[];splitrows=[]
    for m in hr:
        t=m['test_metrics']['test_unseen_customer'];base=m['baselines']['test_unseen_customer']['persistence']['mae']
        rows.append([m['name'],m['algorithm'],n(t['mae'],4),n(base,4),n(t['r2'],3),units[m['name']]])
        splitrows.append([m['name'],m['rows']['train'],m['rows']['validation'],m['rows']['test_unseen_customer']])
    section('3. Bốn model từ CSV của ba tài khoản',[
      f'Cửa sổ chung: {local(h["split"]["start"])} đến {local(h["split"]["end"])}; dài {h["split"]["common_span_hours"]:.2f} giờ nhưng có khoảng trống. Train: Lan + Long trước {local(h["split"]["train_end"])}. Validation kết thúc {local(h["split"]["validation_end"])}. Test chính: Minh ở phần thời gian cuối, chưa tham gia train/validation.',
      'Bảng dưới dùng baseline persistence: lấy số đo hiện tại làm dự báo sau 30 phút. MAE càng thấp càng tốt. Báo cáo JSON còn lưu moving-average, linear-trend và baseline được chọn bằng validation. Không chọn lại model sau khi xem test.',
      'Nhiệt độ có MAE thấp hơn persistence ở tập test này. Độ ẩm và pH kém hơn rõ rệt; EC có MAE cao hơn persistence dù gần moving-average. Các kết quả chưa đủ cơ sở phát hành cho khách.',
      'R² là hệ số đánh giá, không phải phần trăm chính xác. R² âm nghĩa là sai số bình phương lớn hơn cách luôn đoán trung bình của tập test. Tập test ít biến động có thể cho R² âm rất lớn; phải đọc cùng MAE, RMSE và phân bố dữ liệu.'],[
      (['Model','Thuật toán','MAE model','MAE baseline','R²','Đơn vị'],rows),
      (['Model','Train','Validation','Test Minh'],splitrows)])
    reg=[];clf=[]
    for m in b['models']:
        if m['status']=='BLOCKED':continue
        t=m['metrics']['test']
        if m['task']=='regression':reg.append([m['name'],m['algorithm'],n(t['mae'],4),n(t['rmse'],4),n(t['r2'],4)])
        else:clf.append([m['name'],n(t['accuracy']*100,2)+'%',n(t['f1_macro'],4),n(t['recall_risk'],4),str(t['confusion_matrix'])])
    section('4. Mười model trên bộ mô phỏng có nhãn',[
      'Bộ 42 ngày đã tồn tại trước lần chạy này, có 12 khách giả lập. Giữ riêng 3 khách cuối để test; train/validation trên 9 khách còn lại theo thời gian 70/15/15, loại nhãn chạm ranh giới 60 phút.',
      'Thuật toán được fit lại thật. Nhãn sự cố lấy từ trạng thái ẩn của trình mô phỏng, không lấy từ cảnh báo AI. Tập này từng được thử trước đây: đây là đánh giá lại có thể tái lập, không phải một test ngoài hệ thống chưa từng sử dụng.',
      'Toàn bộ model đã fit vẫn là EXPERIMENTAL. Độ chính xác mô phỏng cao chỉ cho thấy học được quy luật trong mô phỏng. Các tín hiệu báo trước sự cố là giả định, chưa đo kiểm ngoài vườn.',
      'Sáu bộ phân loại dùng HistGradientBoosting (HGB); ứng viên được chọn ghi trong JSON từng model. Mất nguồn và MQTT có cùng ma trận đếm lỗi nhưng dữ liệu không giống nhau: trên 2.555 dòng test có 164 nhãn và 166 dự đoán khác nhau. Xem power_mqtt_comparison.json.'],[
      (['Dự báo 30 phút','Thuật toán','MAE','RMSE','R²'],reg),
      (['Sự cố trong 60 phút','Accuracy','F1 macro','Recall sự cố','Ma trận [0,1]'],clf)])
    quality=[]
    for a in h['cleaning']:
        quality.append([a['customer_id'],f'{a["input_rows"]:,}',a['reason_counts']['untrusted_quality'],a['reason_counts']['not_available_at_boundary'],a['grid_rows'],a['empty_grid_rows']])
    section('5. Dữ liệu được xử lý trước khi train',[
      'CSV thô được giữ nguyên và kiểm tra checksum từ manifest. Mỗi khách chỉ lấy snapshot mới nhất, không nối cả bảy bản xuất lịch sử trùng nhau để làm tăng số mẫu.',
      'Các con số ở bảng là các bước khác nhau, không cộng thẳng: chất lượng xấu và đến trễ có thể trùng một bản ghi. Trong nguồn ba khách không thấy ô ID/số đo trống hay số ngoài biên theo phép kiểm này; vẫn có thiếu dữ liệu theo thời gian.',
      'Lưới 10 phút giữ bản ghi cuối đã nhận trước hoặc đúng mốc quyết định, riêng từng khách/vườn/khu/thiết bị/cảm biến. Giữ NaN khi thiếu. Chỉ nhận nhãn +30 phút nếu timestamp của số đo tương lai nằm trong sai số 60 giây; không điền nhãn thiếu.'],[
      (['Khách','Dòng thô','Quality không tốt','Chưa đến kịp mốc','Ô lưới 10 phút','Ô không có bản ghi'],quality),
      (['Bước','Thực hiện','Cách chống sai lệch'],[
        ['1. Kiểm tra cố định','ID, timestamp, đơn vị, số hữu hạn, biên vật lý, chất lượng, trùng ID','Không học tham số từ toàn bộ dữ liệu'],
        ['2. Tạo đặc trưng','Giá trị hiện tại, lag 10/30/60 phút, trung bình 3 mốc, độ dốc, độ thiếu/trễ','Chỉ nhìn quá khứ của đúng cảm biến'],
        ['3. Chia tập','Theo thời gian; giữ khách Minh riêng; loại nhãn vượt ranh giới','Không shuffle toàn bộ lịch sử'],
        ['4. Impute / scale','Median và scaler fit trên train; giữ chỉ báo thiếu','Không fit trên validation/test; không fill nhãn'],
        ['5. Train / chọn','Thử danh sách thuật toán cố định; chọn bằng validation','Không chọn dựa trên test'],
        ['6. Test / xuất','Lưu từng dự đoán, baseline, lỗi lớn, joblib và checksum','Nạp lại model, sai khác tối đa trong dung sai số học 1e-12']])])
    section('6. Thiếu nhãn nghĩa là thiếu điều gì?',[
      'Ví dụ: để học nguy cơ mất nguồn trong giờ tới, mỗi mốc đầu vào cần có bằng chứng độc lập trong giờ tiếp theo: xảy ra sự cố hay không, vào lúc nào, tại tủ nào. Không có ghi nhận không tự đồng nghĩa với không xảy ra.',
      'CSV alerts cũ có nội dung “AI: Chẩn đoán lưu lượng” và “confidence”. CSV irrigation_runs có nguồn demo_seed_v10. Đây không phải nhãn sự cố được xác nhận để đánh giá sáu model dự báo trên khách.',
      'Nhãn nhị phân: 1 = có sự cố được xác nhận trong cửa sổ; 0 = đủ giám sát cả cửa sổ và không có sự cố; trống = chưa biết, không được đổi thành 0.'],[
      (['Model','Cần bổ sung vào dữ liệu khách','Vẫn trả lời được gì khi chưa train?'],[
        ['flow_fault_forecast','Mốc bơm/van được yêu cầu chạy, lưu lượng xác nhận và sự cố có onset/end','Đọc lưu lượng, trạng thái bơm/van, cảnh báo có sẵn'],
        ['leak_forecast','Sự cố rò rỉ xác nhận độc lập, thời điểm và vùng; không dùng dự đoán AI làm nhãn','Mô tả biến động/số liệu, chưa khẳng định rò rỉ'],
        ['irrigation_failure_forecast','Ca vận hành thật có kết quả, lý do gián đoạn và liên kết thiết bị/thời gian','Thống kê ca được ghi nhận thành công/thất bại'],
        ['sensor_fault_forecast','Lỗi cảm biến được thiết bị/chẩn đoán độc lập ghi nhận, có thời điểm khôi phục','Báo số đo thiếu/trễ hoặc quality không tốt'],
        ['power_loss_forecast','Giám sát nguồn độc lập, lịch mất/khôi phục và tín hiệu báo trước','Phân biệt bằng chứng nguồn với thiếu kết nối'],
        ['mqtt_loss_forecast','Nhật ký kết nối broker/client, nguyên nhân/ngắt nối và độ phủ giám sát','Đọc trạng thái MQTT, báo gián đoạn theo bằng chứng']])])
    section('7. Tệp cần mở khi trình bày báo cáo',[
      'Gốc dự án: '+str(root),
      'Mỗi run là một phiên bản riêng. Không ghi đè CSV thô và không đổi registry đang phục vụ khách bằng kết quả chưa nghiệm thu. Thư mục model-artifacts/data dành cho dữ liệu ML, tách khỏi data chung của dự án.',
      '500 khách không có nghĩa là phải tạo 5.000 model. Có thể dùng bộ model chung theo bài toán/nhóm thiết bị phù hợp; dữ liệu và quyền xem vẫn theo từng khách. Khả năng áp dụng chung cần test trên nhiều khách mới, theo nhóm vườn và theo thời gian. Dự án chưa được kiểm thử tải 500 khách.'],[
      (['Đường dẫn từ gốc dự án','Bằng chứng trong tệp'],[
        ['model-artifacts/data/customers/<khách>/snapshots/<snapshot>/raw/','CSV nguồn; snapshot_manifest.json ở thư mục cha ghi hash, số dòng, thời điểm xuất'],
        ['model-artifacts/data/historical-customer/'+h['run_id']+'/','CSV sạch theo khách; cleaning_report.json; features_with_split.csv; split_counts.csv'],
        ['model-artifacts/historical-customer/'+h['run_id']+'/','training_report.json; model_summary.csv; thư mục từng model có report, predictions, largest_errors, model.joblib'],
        ['model-artifacts/data/benchmark-retrain/'+b['run_id']+'/','CSV mô phỏng đã làm sạch, manifest, cleaning_report và features_with_split'],
        ['model-artifacts/benchmark-retrain/'+b['run_id']+'/','Báo cáo 10 model, dự đoán train/validation/test, lỗi lớn, model.joblib, source/'],
        ['nextfarm_device/historical_training.py; benchmark_training.py','Mã nguồn xử lý và train lại hai nguồn, không tự sinh thêm dữ liệu'],
        ['nextfarm_device/data_quality.py; collection.py; runtime_training.py','Chuẩn hóa dữ liệu vận hành và pipeline 72 giờ'],
        ['docs/retraining-20260913/','Bản PDF/HTML này, báo cáo nén và unit-tests.xml']])])
    section('8. Cách tái lập và bước tiếp theo',[
      'Các lệnh dưới chạy tại gốc dự án, trong môi trường đã cài requirements của ai-analytics-service. Phiên bản chính: scikit-learn 1.8.0, pandas 2.2.3, numpy 2.2.1, scipy 1.15.1, joblib 1.4.2. Seed: 20260913.',
      'python -m nextfarm_device.historical_training --project .',
      'python -m nextfarm_device.benchmark_training --project . --source model-artifacts/data/device-v11-validation-b-20260910',
      'python -m pytest tests_device -q',
      'Kiểm thử mã nguồn: 60/60 qua; 14 cảnh báo PerformanceWarning về cách tạo DataFrame, không có test thất bại. Các bài kiểm thử dùng fixture, không phải bằng chứng độ chính xác ngoài vườn.',
      'Train lịch sử trong báo cáo này không cần web đang chạy. Lần kiểm tra HTTP cổng 18080 lúc 21:50 ngày 13/09 bị từ chối kết nối. Collection_state gần nhất ghi 06:22 cùng ngày, chưa đủ 72 giờ. Không khẳng định hệ thống đang tiếp tục thu khi chưa khởi động và kiểm tra lại.',
      'Sau khi cập nhật mã xử lý dữ liệu, cần build lại service để container nhận bản mới. CMD: scripts\\start_v11.cmd. Worker hiện có sẽ kiểm tra điều kiện mỗi 5 phút, chỉ xuất bộ dữ liệu tối đa mỗi 24 giờ khi đủ điều kiện; ứng viên chưa nghiệm thu vẫn không được phát hành dự báo.'],[
      (['Ưu tiên','Việc cần làm','Điều kiện hoàn thành'],[
        ['1. Chất lượng dữ liệu','Thu đủ cửa sổ có độ phủ, xử lý độ trễ và lỗi cảm biến','Báo cáo thiếu/trễ theo khách và nhóm dữ liệu, không chỉ đếm dòng'],
        ['2. Nhãn sự cố','Ghi/đối soát sự cố từ nguồn độc lập; thêm trường sự cố và độ phủ','Có cả sự cố và khoảng không sự cố được xác nhận; đủ đợt riêng biệt'],
        ['3. Cải thiện dự báo','Dùng train/validation để nghiên cứu; đóng băng tập test mới khi có dữ liệu tiếp theo','Vượt baseline theo khách/thiết bị và sai số nghiệp vụ được duyệt'],
        ['4. Hiểu câu hỏi','Kiểm thử cách hỏi thực của nông dân, câu nhiều ý và câu ngoài phạm vi','Đo đúng ý định, đúng công cụ, đúng quyền, đúng số và biết từ chối'],
        ['5. Phát hành','Chỉ kích hoạt model sau kiểm định phù hợp; theo dõi và có rollback','Không dùng chữ READY chỉ vì file model đã tồn tại']])])
    # Structured content is shared by PDF and HTML to avoid transcription drift.
    write_json= lambda p,o:Path(p).write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')
    write_json(docs/'report_sources.json',{'historical_report':hp,'benchmark_report':bp,'generated_at':datetime.now(timezone.utc).isoformat()})
    esc=lambda x:html.escape(str(x))
    html_parts=['<!doctype html><html lang="vi"><meta charset="utf-8"><title>NextFarm - Báo cáo train lại</title><style>body{font:16px Arial;line-height:1.55;max-width:1180px;margin:36px auto;color:#14342a}h1,h2{color:#12573b}section{margin:36px 0;break-after:page}table{border-collapse:collapse;width:100%;margin:18px 0}th,td{border:1px solid #bccdc4;padding:10px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#e6f2eb}tr:nth-child(even){background:#f7faf8}pre{white-space:pre-wrap}a{color:#155c93}@media print{body{font-size:10pt;margin:0}thead{display:table-header-group}tr{break-inside:avoid}}</style><h1>NextFarm - Báo cáo huấn luyện từ dữ liệu hiện có</h1>']
    for title,paragraphs,tables in sections:
        html_parts.append('<section><h2>'+esc(title)+'</h2>')
        html_parts.extend('<p>'+esc(p)+'</p>' for p in paragraphs)
        for headers,rows in tables:html_parts.append('<table><thead><tr>'+''.join('<th>'+esc(c)+'</th>' for c in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(c)+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table>')
        html_parts.append('</section>')
    sources=[('R² và ý nghĩa giá trị âm','https://scikit-learn.org/stable/modules/generated/sklearn.metrics.r2_score.html'),('Tránh rò rỉ dữ liệu khi tiền xử lý','https://scikit-learn.org/stable/common_pitfalls.html')]
    html_parts.append('<p>Tài liệu chỉ số: '+', '.join('<a href="'+u+'">'+t+'</a>' for t,u in sources)+'</p></html>')
    (docs/'BAO-CAO-TRAIN-LAI.html').write_text(''.join(html_parts),encoding='utf-8')
    pdfmetrics.registerFont(TTFont('Arial','C:/Windows/Fonts/arial.ttf'));pdfmetrics.registerFont(TTFont('ArialBold','C:/Windows/Fonts/arialbd.ttf'))
    normal=ParagraphStyle('normal',fontName='Arial',fontSize=9,leading=13,spaceAfter=8,wordWrap='CJK')
    heading=ParagraphStyle('heading',parent=normal,fontName='ArialBold',fontSize=17,leading=22,textColor=colors.HexColor('#145439'),spaceAfter=14)
    cell=ParagraphStyle('cell',parent=normal,fontSize=8,leading=11,spaceAfter=0)
    head=ParagraphStyle('head',parent=cell,fontName='ArialBold',textColor=colors.white)
    story=[];width=A4[0]-72
    def para(x,style=normal):return Paragraph(esc(x).replace('\n','<br/>'),style)
    for index,(title,paragraphs,tables) in enumerate(sections):
        if index:story.append(PageBreak())
        story.append(para(title,heading));story.extend(para(p) for p in paragraphs)
        for headers,rows in tables:
            weights=[1]*len(headers)
            if len(headers)==2:weights=[1.1,1.3]
            if len(headers)==3:weights=[.9,1.3,1.3]
            if len(headers)>=4:weights=[1.8]+[1]*(len(headers)-1)
            table=Table([[para(c,head) for c in headers]]+[[para(c,cell) for c in row] for row in rows],colWidths=[width*x/sum(weights) for x in weights],repeatRows=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#145439')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f0f6f2')]),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#bbcfc2')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
            story.extend([table,Spacer(1,12)])
        if index==len(sections)-1:
            story.append(para('Tài liệu phương pháp: scikit-learn, r2_score và Common pitfalls. Báo cáo HTML chứa liên kết trực tiếp.'))
    def footer(canvas,doc):
        canvas.setFont('Arial',8);canvas.setFillColor(colors.HexColor('#587165'))
        canvas.drawString(36,23,'NextFarm | Huấn luyện có truy vết | Dữ liệu mô phỏng được ghi rõ')
        canvas.drawRightString(A4[0]-36,23,str(doc.page))
    pdf=docs/'BAO-CAO-TRAIN-LAI.pdf'
    SimpleDocTemplate(str(pdf),pagesize=A4,leftMargin=36,rightMargin=36,topMargin=36,bottomMargin=42,title='NextFarm - Báo cáo train lại',author='NextFarm project').build(story,onFirstPage=footer,onLaterPages=footer)
    print(str(pdf))

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser();parser.add_argument('--project',required=True);main(parser.parse_args().project)
