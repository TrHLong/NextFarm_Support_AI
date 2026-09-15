"""Generate a Word report and Markdown from actual run artifacts, never hard-coded scores."""
import json,sys,html,collections
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timezone
from docx import Document
from docx.shared import Inches,Pt,RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT

root=Path(sys.argv[1]) if len(sys.argv)>1 else Path(r'D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1')
sys.path.insert(0,str(root))
from nextfarm_device.contracts import RULE_CAPS
report=json.loads((root/'model-artifacts/device-v11/latest_training_report.json').read_text(encoding='utf-8'))
audit=json.loads((root/'docs/device-v11/acceptance.json').read_text(encoding='utf-8'))
unit_suite=ET.parse(root/'docs/device-v11/unit-tests.xml').getroot().find('testsuite')
unit_count=int(unit_suite.get('tests'));assert int(unit_suite.get('errors','0'))==int(unit_suite.get('failures','0'))==0
manifest=json.loads(Path(report['source_manifest']).read_text(encoding='utf-8'))
out=root/'docs/device-v11';out.mkdir(parents=True,exist_ok=True)
doc=Document();section=doc.sections[0];section.page_width=Inches(8.5);section.page_height=Inches(11)
section.top_margin=section.bottom_margin=Inches(.65);section.left_margin=section.right_margin=Inches(.7)
for name in ['Normal','Title','Subtitle','Heading 1','Heading 2','Header','Footer']:
    style=doc.styles[name];style.font.name='Arial';style.font.color.rgb=RGBColor(0,0,0)
doc.styles['Normal'].font.size=Pt(10.5);doc.styles['Normal'].paragraph_format.space_after=Pt(6)
doc.styles['Normal'].paragraph_format.line_spacing=1.08
doc.styles['Title'].font.size=Pt(23);doc.styles['Heading 1'].font.size=Pt(16);doc.styles['Heading 2'].font.size=Pt(12)
header=section.header.paragraphs[0];header.text='NEXTFARM   |   BẢN THIẾT BỊ V11   |   KIỂM CHỨNG NGÀY 10 09 2026';header.style='Header';header.runs[0].font.size=Pt(8)
footer=section.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT
footer.add_run('Kiểm định mô phỏng   •   Trang ')
field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
md=[];html_parts=[]
def p(text,bold=False):
    para=doc.add_paragraph();r=para.add_run(text);r.bold=bold;md.append(text+'\n');html_parts.append('<p>'+html.escape(text)+'</p>')
def h(text,level=1):
    doc.add_heading(text,level);md.append('#'*(level+1)+' '+text+'\n');html_parts.append(f'<h{level+1}>'+html.escape(text)+f'</h{level+1}>')
def page(text):doc.add_page_break();h(text)
def table(headers,rows,widths=None):
    t=doc.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
    widths=widths or [7.1/len(headers)]*len(headers)
    for c,w in zip(t.columns,widths):c.width=Inches(w)
    borders=OxmlElement('w:tblBorders')
    for name in ['top','left','bottom','right','insideH','insideV']:
        b=OxmlElement('w:'+name);b.set(qn('w:val'),'single');b.set(qn('w:sz'),'4');b.set(qn('w:color'),'D9D9D9');borders.append(b)
    t._tbl.tblPr.append(borders)
    for i,values in enumerate([headers]+rows):
        row=t.rows[0] if i==0 else t.add_row();cant=OxmlElement('w:cantSplit');row._tr.get_or_add_trPr().append(cant)
        if i==0:
            repeat=OxmlElement('w:tblHeader');row._tr.get_or_add_trPr().append(repeat)
        for j,(cell,value) in enumerate(zip(row.cells,values)):
            cell.width=Inches(widths[j]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cp=cell._tc.get_or_add_tcPr();shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'173F55' if i==0 else ('EFF4F7' if i%2==0 else 'FFFFFF'));cp.append(shade)
            margins=OxmlElement('w:tcMar')
            for side in ['top','bottom','left','right']:
                v=OxmlElement('w:'+side);v.set(qn('w:w'),'80');v.set(qn('w:type'),'dxa');margins.append(v)
            cp.append(margins);para=cell.paragraphs[0];para.paragraph_format.space_after=Pt(1);para.paragraph_format.space_before=Pt(1);para.paragraph_format.line_spacing=1.05
            r=para.add_run(str(value));r.font.size=Pt(9);r.bold=i==0;r.font.color.rgb=RGBColor(255,255,255) if i==0 else RGBColor(0,0,0)
    doc.add_paragraph().paragraph_format.space_after=Pt(2)
    md.append('| '+' | '.join(headers)+' |\n| '+' | '.join('---' for _ in headers)+' |\n'+'\n'.join('| '+' | '.join(str(x).replace('\n','<br>').replace('|','/') for x in row)+' |' for row in rows)+'\n')
    html_parts.append('<table><thead><tr>'+''.join('<th>'+html.escape(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x)).replace('\n','<br>')+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table>')
def num(value,n=4):return f'{value:.{n}f}'
titles={'moisture_forecast':'Độ ẩm đất','temperature_forecast':'Nhiệt độ','ec_forecast':'EC','ph_forecast':'pH','flow_fault_forecast':'Mất lưu lượng','leak_forecast':'Rò rỉ','irrigation_failure_forecast':'Ca tưới gián đoạn','sensor_fault_forecast':'Sự cố cảm biến','power_loss_forecast':'Mất nguồn','mqtt_loss_forecast':'Mất MQTT'}
group_vi={'sensor_readings':'Số đo cảm biến','device_status':'Trạng thái tủ','irrigation_schedules':'Lịch tưới','irrigation_runs':'Lịch sử tưới','control_commands':'Nhật ký lệnh','alerts':'Cảnh báo','device_profile':'Hồ sơ tủ','connection_observer':'Giám sát độc lập'}
doc.add_paragraph('Báo cáo kiểm chứng NextFarm phiên bản thiết bị',style='Title')
doc.add_paragraph('Bản Word chờ kiểm tra phân trang. Số liệu đồng bộ với báo cáo HTML cùng thư mục.')
md.append('# Báo cáo kiểm chứng NextFarm phiên bản thiết bị\n');html_parts.append('<h1>Báo cáo kiểm chứng NextFarm phiên bản thiết bị</h1>')
p('Báo cáo giúp người thực hiện giải thích bản sửa với giảng viên: dữ liệu ở đâu, bot hiểu câu hỏi bằng cách nào, model học và được đo ra sao, và phần nào chưa đạt yêu cầu. Các số liệu dưới đây lấy trực tiếp từ artifact và kiểm thử của phiên bản được nêu.')
p(f'Kết luận: {report["ready_count"]}/10 model đạt quality gate trên dữ liệu mô phỏng. '+('Đã đạt mốc 10/10 READY trong phạm vi thí nghiệm này; chưa có kiểm định thực địa. ' if report['ready_count']==10 else 'Chưa đạt yêu cầu 10/10 READY và chưa có kiểm định thực địa. ')+'32 năng lực hỗ trợ đã được triển khai bằng truy vấn, quy tắc và kiểm tra dữ liệu; đây không phải 32 model được huấn luyện.',True)
table(['Nội dung yêu cầu','Kết quả hiện tại'],[
 ['Bỏ ticket và kỹ thuật viên trực chat','Đã sửa giao diện, API trả 410 cho ticket; kỹ thuật viên bị chặn chat, được xem dữ liệu theo quyền và duyệt Knowledge.'],
 ['Mỗi cuộc chat gắn một tủ','Bắt buộc device_id; xác thực tài khoản và farm trước khi đọc dữ liệu.'],
 ['Hai tình huống mất dữ liệu','Mất nguồn và mất MQTT được tách theo giám sát độc lập. Thiếu bằng chứng trả chưa xác định.'],
 ['Kiểm thử bản mới',f'{audit["passed"]}/{audit["total"]} ca API; {unit_count}/{unit_count} kiểm tra logic. Đây là tỷ lệ ca kiểm thử đạt, không phải độ chính xác AI.'],
 ['10 model chính',f'{report["ready_count"]} READY mô phỏng, {10-report["ready_count"]} EXPERIMENTAL; chỉ artifact đủ điều kiện được gọi.'],
 ['Tri thức công ty','18 mục được nhập dạng bản nháp, chờ kỹ thuật viên duyệt. Chưa duyệt thì chatbot chưa dùng.'],
 ['Chạy và build','Bản chạy thử cục bộ ở 19080 đã kiểm tra. Chưa xác nhận build Docker vì phiên làm việc bị từ chối quyền truy cập Docker Engine.']],[1.75,5.35])
p('Thư mục dự án: '+str(root))
p('Phiên bản dữ liệu và model: '+report['dataset_version'])

page('Luồng câu hỏi và phân quyền')
p('Luồng đang chạy dùng bộ định tuyến quy tắc tiếng Việt, API đọc dữ liệu và mẫu diễn giải có bằng chứng. Không gọi ChatGPT, OpenAI hay Gemini; không có MCP server trong luồng này. Model ML dự báo được gọi ở nhánh dự báo, không nhận trực tiếp câu hỏi văn bản.')
table(['Bước','Xử lý thật','Dấu vết kiểm chứng'],[
 ['1','Đăng nhập nhận token; chọn một tủ thuộc danh sách được cấp quyền.','POST /auth/login; GET /devices'],
 ['2','Chuẩn hóa dấu tiếng Việt, nhận chỉ số, ý định và khoảng thời gian; câu ghép có thể gọi nhiều công cụ.','answers.py → route; trace.plan'],
 ['3','Farm API kiểm tra lại tài khoản và device_id, trả dữ liệu kèm customer_id và thời điểm.','store.authorize_device; device_db.read_audits'],
 ['4','Hỏi hiện tại: tính từ dữ liệu. Hỏi tương lai: chọn đúng model; thiếu điều kiện thì từ chối dự báo.','api.chat_app; api.analytics_app'],
 ['5','Kiểm tra độ mới, nguồn và chất lượng; dựng câu trả lời, lưu nguồn số liệu và công cụ đã gọi.','device_db.chat_log.trace'],
 ['6','Phản hồi hữu ích/chưa đúng được lưu để rà soát; không tự biến lời khách hàng thành nhãn train.','device_db.chat_feedback; training_use_allowed=false']],[.45,3.85,2.8])
h('Ví dụ có thể trình bày',2)
p('“Độ ẩm 62% có cao không?”: bot đọc số đo thật của tủ, tách 62% là số khách hàng nhập chưa xác minh, rồi so với ngưỡng cấu hình. Ngưỡng hiện tại là cấu hình demo, chưa phải tiêu chuẩn nông học cho mọi cây trồng.')
p('“Dự báo độ ẩm đất sau 30 phút”: chỉ gọi model độ ẩm đất nếu dữ liệu mới và hợp lệ. “Dự báo độ ẩm không khí”: hiện không có model tương ứng nên phải nói chưa phát hành dự báo, không lấy model khác thay thế. “Giá vàng ngày mai” là ngoài phạm vi, không được nhận từ vàng thành van.')
p('“Tủ không gửi dữ liệu nữa”: giám sát độc lập mới xác nhận có mất nguồn hay vẫn có nguồn nhưng MQTT lỗi. Khi chỉ thấy trạng thái cũ, bot nói chưa đủ bằng chứng. Giám sát độc lập trong demo là mô phỏng tại server; hệ thống thật cần kênh nguồn độc lập tương ứng.')
p('Cơ chế quy tắc chưa chứng minh hiểu mọi cách diễn đạt. Câu chưa khớp công cụ hoặc tri thức đã duyệt sẽ yêu cầu bổ sung thông tin; không dùng LLM tự viết số liệu.')

page('Dữ liệu nguồn và phạm vi mô phỏng')
table(['Nhóm','Nhịp trong bản mới','Cách sử dụng'],[
 ['Số đo cảm biến','Gửi 60 giây; lưu một mẫu mỗi 10 phút','Số đo hiện tại, lịch sử và đặc trưng model.'],
 ['Trạng thái tủ','MQTT mỗi 5 giây khi có nguồn và mạng','Bơm/van/phân và độ mới trạng thái. CSV thí nghiệm lấy mẫu 10 phút, không đếm như toàn bộ gói MQTT.'],
 ['Lịch tưới','Theo cấu hình','Lịch tại bo; mất MQTT có thể vẫn chạy.'],
 ['Lịch sử tưới','Theo sự kiện kết thúc/gián đoạn','Tổng lượng đo hợp lệ, thời lượng và kết quả; counter reset không được coi là 0.'],
 ['Nhật ký lệnh','Theo sự kiện','Người ra lệnh, thời gian, kết quả xác nhận. Lệnh gửi không chứng minh relay đã chạy.'],
 ['Cảnh báo','Khi chuyển trạng thái','Nguồn, MQTT hoặc thiếu bằng chứng.'],
 ['Hồ sơ khách hàng và tủ','Theo cấu hình','Quyền dữ liệu, ánh xạ ngõ ra, cảm biến và ngưỡng demo.']],[1.35,2.7,3.05])
p('Tài liệu gốc: docs/references/Chat-thiet-bi-NextFarm-v0.1.html. Phần cứng, kiểu dữ liệu và liên động dựa theo đặc tả. Biên độ dao động, nhiễu, tần suất sự cố và độ mạnh dấu hiệu báo trước là giả định mô phỏng, chưa hiệu chỉnh bằng đo thực tế.')
p('Điện áp, áp suất, dòng bơm, số lỗi bus và packet loss là các trường bổ sung để nghiên cứu. Chưa xác nhận tất cả tủ thực của công ty có đủ thiết bị đo và API cho các trường này. Mất điện đột ngột không có dấu hiệu báo trước vẫn có thể không dự báo được.')
counts=collections.Counter()
for item in manifest['files']:counts[Path(item['path']).stem]+=item['rows']
table(['Bộ thí nghiệm','Số liệu'],[['Khách hàng mô phỏng / thật',f'{report["synthetic_customers"]} / 0'],['Thời gian / mốc thời gian',f'{report["duration_days"]} ngày / {report["unique_timestamps"]:,} mốc'],['Số dòng đặc trưng',f'{report["processed_rows"]:,}'],['Sensor / status CSV',f'{counts["sensor_readings"]:,} / {counts["device_status"]:,}'],['Ground truth / sự kiện',f'{counts["incident_ground_truth"]:,} / {counts["incidents"]:,}'],['Lịch sử tưới / lệnh',f'{counts["irrigation_runs"]:,} / {counts["control_commands"]:,}']],[3,4.1])
p('68 nghìn dòng không đồng nghĩa 68 nghìn quan sát độc lập: dữ liệu có tự tương quan và chỉ có 12 chuỗi khách hàng mô phỏng. Dữ liệu demo đang chạy của ba tài khoản được lưu riêng, không đổi tên thành 12 khách hàng thật.')

page('Quy trình từ CSV đến artifact')
p('CSV đầu vào: '+str(Path(report['source_manifest']).parent))
p('Mỗi thư mục customers/synthetic_customer_XXX chứa sensor_readings.csv, device_status.csv, incident_ground_truth.csv cùng lịch sử tưới, lệnh, sự kiện và hồ sơ. customer_id và device_id dùng đối chiếu, không đưa vào đặc trưng học.')
table(['Công đoạn','Cách thực hiện'],[
 ['Xác minh nguồn','Kiểm tra SHA256 trong manifest.json; không ghi đè bộ dữ liệu cũ khi --generate.'],
 ['Lọc và làm sạch','Chuẩn hóa UTC, sắp thời gian, loại trùng timestamp, chuyển kiểu số. Số đo bad/suspect và dữ liệu thiếu giữ NaN; không giả định mất kết nối hoặc packet loss bằng 0.'],
 ['Tạo đặc trưng','Số đo hiện tại, lag 1/3/6 điểm, trung bình 3 điểm, tốc độ thay đổi theo phút, cờ thiếu. Ghép trạng thái chỉ lùi tối đa 30 giây. Regression chỉ dùng chuỗi của chính chỉ số và cần số đo hiện tại hợp lệ.'],
 ['Tạo target','Regression: giá trị sau 30 phút, khớp thời gian ±60 giây. Classification: có sự cố khởi phát trong 60 phút tiếp theo; loại dòng đang trong chính sự cố đó.'],
 ['Chia dữ liệu','9 khách hàng phát triển: train 70% đầu và validation 15% tiếp. Test là 15% cuối của 3 khách hàng hoàn toàn chưa học. Purge theo thời điểm kết thúc nhãn.'],
 ['Fit và chọn model','Imputer và bộ lọc đặc trưng chỉ fit trên train. Chọn ứng viên bằng validation. Không refit hoặc hiệu chỉnh xác suất sau test.'],
 ['Đo và xuất','So với baseline, kiểm tra từng khách hàng giữ lại. Lưu dự đoán CSV, số liệu theo khách, confusion matrix, hash model và code train. READY mới vào active_models.json.']],[1.25,5.85])
table(['Phân vùng trước lọc target','Số dòng'],[[k,f'{v:,}'] for k,v in report['split_counts'].items()],[4.5,2.6])
p('Test đã được dùng cho báo cáo chất lượng và quyết định phát hành, nên đây là test của thí nghiệm đã công bố. Nếu tiếp tục chọn thiết kế theo kết quả này, cần khóa một bộ test mới trước lần khẳng định tiếp theo; không train lại nhiều lần để chọn bảng đẹp nhất.')

page('Bốn model dự báo số đo')
regs=[m for m in report['models'] if m['task']=='regression']
table(['Model','MAE macro','Baseline tốt nhất','Cải thiện MAE','Trạng thái'],[[titles[m['name']],num(m['macro_metric']),num(min(m['baseline_macro'].values())),f'{m["baseline_gain"]*100:+.2f}%',m['status']] for m in regs],[1.3,1.2,1.4,1.45,1.75])
p('MAE là sai số tuyệt đối trung bình, cùng đơn vị với chỉ số: độ ẩm tính theo điểm phần trăm, nhiệt độ °C, EC mS/cm, pH theo đơn vị pH. MAE càng thấp càng tốt. Không đổi R² thành “phần trăm chính xác”. Macro ở đây là trung bình MAE của ba khách hàng test, để mỗi khách có trọng số bằng nhau.')
p('Baseline gồm giữ nguyên số đo cuối, trung bình trượt 3 điểm và ngoại suy tuyến tính. Gate đã đặt trước: cải thiện MAE macro tối thiểu 3% so với baseline tốt nhất và tốt hơn baseline ở từng khách hàng test.')
for m in regs:
    h(titles[m['name']],2)
    p(f'Train {m["train_rows"]:,}, validation {m["validation_rows"]:,}, test {m["test_rows"]:,} dòng có target. Thuật toán được chọn: {m["algorithm"]}. '+('Đạt cả điều kiện trung bình và từng khách hàng trong mô phỏng.' if m['status']=='READY' else 'Chưa chứng minh tốt hơn baseline; không phát hành dù model đã được huấn luyện.'))
table(['Khách test','Độ ẩm MAE','Nhiệt độ MAE','EC MAE','pH MAE'],[[site]+[num(m['per_customer'][site]['model']['mae']) for m in regs] for site in report['held_out_customers']],[2.3,1.2,1.2,1.2,1.2])
p('Thí nghiệm trước chỉ đạt 6/10. Lần này giữ nguyên gate, bổ sung Ridge tự hồi quy cạnh Extra Trees và HistGradientBoosting, dùng đặc trưng của chính chỉ số, và chỉ chấm trường hợp đầu vào hiện tại hợp lệ giống điều kiện inference. Các ứng viên được chọn bằng validation; seed 20260911 được ghi trước khi mở bộ test mới. Cải thiện giữa hai lần không phải nghiên cứu ablation vì cả thiết kế và bộ mô phỏng đã đổi; cần thí nghiệm đối chứng nếu muốn quy kết mức tăng cho riêng từng thay đổi. Các kết quả kém trước đó vẫn được giữ.')

page('Sáu model dự báo sự cố')
cls=[m for m in report['models'] if m['task']=='classification']
table(['Model','F1 macro theo khách','F1 baseline','Chênh lệch','Trạng thái'],[[titles[m['name']],num(m['macro_metric']),num(max(m['baseline_macro'].values())),f'{m["baseline_gain"]:+.4f}',m['status']] for m in cls],[1.45,1.35,1.25,1.25,1.8])
p('F1 kết hợp precision và recall. Mỗi khách được tính F1 macro trên hai lớp có/không có sự cố; sau đó lấy trung bình ba khách. Accuracy pooled và confusion matrix vẫn được lưu trong JSON, nhưng không dùng accuracy đơn lẻ để che lớp rủi ro ít xuất hiện.')
p('Gate: F1 macro ≥0,65; tăng ≥0,02 so với baseline tốt nhất; mỗi khách test F1 ≥0,55 và recall lớp sự cố ≥0,50. Trước train cần tối thiểu 50 mẫu mỗi lớp trong train, 10 trong validation và 5 trong từng khách test. Baseline gồm lớp đa số và rule ngưỡng hiện tại.')
table(['Model','Train','Validation','Test','Recall rủi ro thấp nhất'],[[titles[m['name']],m['train_rows'],m['validation_rows'],m['test_rows'],num(min(x['model']['recall_risk'] for x in m['per_customer'].values()))] for m in cls],[1.9,1,1.15,1,2.05])
p('Đã bổ sung tốc độ biến đổi tín hiệu và hai ứng viên HistGradientBoosting có nhiều lá hơn, có/không cân bằng lớp; chọn bằng validation. Ca tưới gián đoạn ở lần này hơn baseline '+f'{next(m for m in cls if m["name"]=="irrigation_failure_forecast")["baseline_gain"]:.4f}'+'. Việc đạt phải đồng thời thỏa mức tăng và từng khách, không dựa vào một F1 cao riêng lẻ.')
p('Các model sự cố READY chỉ chứng minh khớp các dấu hiệu báo trước đã mô phỏng. Nhãn ẩn độc lập với ngưỡng feature tại cùng thời điểm giúp tránh học lại rule, nhưng vẫn không thay thế nhật ký sự cố thực địa do người có chuyên môn xác nhận.')

page('Ba mươi hai năng lực hỗ trợ phần một')
p('Danh sách này tách khỏi 10 model học máy. Năng lực là một thao tác truy vấn, tính toán hoặc kiểm tra có thể tái sử dụng trong câu trả lời; nhiều năng lực dùng chung một công cụ. Không báo “accuracy” cho phép cộng hay kiểm tra quyền. READY trong catalog là có công cụ và nhóm dữ liệu; không bảo đảm có dữ liệu mới ở mọi thời điểm.')
table(['STT','Năng lực','Nhóm bằng chứng'],[[i+1,title,group_vi[group]] for i,(_,title,group) in enumerate(RULE_CAPS[:16])],[.5,4.65,1.95])
p('Khi giám sát độc lập vắng hoặc đã cũ, khả năng chẩn đoán nguyên nhân mất kết nối phải trả chưa xác định. Kết quả kiểm thử hai lỗi nguồn/MQTT được lưu trong acceptance.json cùng nội dung câu trả lời.')
page('Ba mươi hai năng lực hỗ trợ phần hai')
table(['STT','Năng lực','Nhóm bằng chứng'],[[i+17,title,group_vi[group]] for i,(_,title,group) in enumerate(RULE_CAPS[16:])],[.5,4.65,1.95])
p('Các câu hỏi minh họa: “Độ ẩm tuần này cao nhất bao nhiêu?”, “Bơm có chạy không?”, “Vì sao chưa châm phân?”, “Hôm nay tưới mấy lần, bao nhiêu nước?”, “Lệnh nào thất bại?”, “Cảm biến thiếu chỉ số nào?”, “Nguồn câu trả lời và CSV ở đâu?”. Không thực hiện điều khiển bơm hay van từ chat.')
p('Giới hạn: bộ định tuyến còn dựa vào mẫu từ; chưa có benchmark ngôn ngữ diện rộng để tuyên bố hỗ trợ mọi câu hỏi. Các phép tính cho thấy dữ liệu đã ghi nhận, không tự khẳng định sự việc ngoài thực địa khi thiết bị im lặng.')

page('Tự động cập nhật và mở rộng khách hàng')
p('Không train 10 model riêng cho từng khách hàng. Dữ liệu xuất ra vẫn phân biệt customer_id/device_id, sau đó tạo bộ huấn luyện chung và giữ khách chưa từng học để đánh giá. Suy luận luôn chỉ nhận lịch sử của tủ mà tài khoản có quyền đọc.')
table(['Điều kiện tự động hiện tại','Ngưỡng hoặc hành vi'],[
 ['Kiểm tra dữ liệu mới','Worker kiểm tra mỗi 300 giây; xuất snapshot khi tổng có ít nhất 144 sensor mới so với watermark hoặc khởi tạo lần đầu.'],
 ['Từng tủ trước khi train','Ít nhất 2.016 sensor, 2.016 status, 2.016 nhãn sự cố; ít nhất 20 ca tưới và 20 lệnh; khoảng quan sát ≥14 ngày.'],
 ['Độc lập khách hàng','Ít nhất 9 khách hàng; nhiều tủ của cùng khách không làm tăng số khách độc lập. Chọn chuỗi tủ dài nhất mỗi khách, ghi lại lựa chọn.'],
 ['Nguồn và nhãn','Chỉ pool mô phỏng đủ nhãn. Dữ liệu thật bị chặn cho tới khi có hợp đồng nhãn và kiểm định thực địa.'],
 ['Train và phát hành','Dùng lại pipeline và gate đã công bố. Chỉ thay bộ đang chạy khi cả 10 model mới đạt. Nếu ứng viên không đạt, giữ registry cũ và lưu latest_candidate_report.json để giải trình. Ghi registry nguyên tử; suy luận kiểm tra hash.'],
 ['Ba tài khoản demo hiện tại','Chưa đủ số khách/ngày/lớp sự cố để tự train đạt gate. Ghi BLOCKED với lý do, vẫn dùng registry thí nghiệm hợp lệ trong phạm vi mô phỏng.']],[2.2,4.9])
p('Với 500 khách, ý tưởng vẫn là một bộ model chung hoặc một số cohort có chứng cứ, không phải 5.000 model. Mã hiện tại chưa được thử tải 500 khách; truy vấn đếm và xuất dữ liệu hàng loạt cần benchmark, hàng đợi công việc và giới hạn tài nguyên trước khi triển khai ở quy mô đó.')
p('Các ngưỡng số dòng là điều kiện kỹ thuật tối thiểu, không chứng minh đủ chất lượng thống kê. Thiếu lớp sự cố, nhãn không độc lập, phân bố khác hoặc performance kém đều có thể chặn phát hành sau khi đã đủ số dòng.')

page('Bản đồ file và bằng chứng có thể truy nguyên')
p('Tất cả đường dẫn dưới đây tương đối với thư mục dự án đã nêu ở trang đầu. Bảng kết quả cũ là bằng chứng lịch sử của v10; không dùng thay báo cáo v11 này.')
table(['File hoặc thư mục','Nội dung để kiểm tra'],[
 ['nextfarm_device/contracts.py','10 target và 32 năng lực; tên và phạm vi không đánh đồng với nhau.'],
 ['nextfarm_device/simulation.py','Giả định vật lý, seed, nhiễu, tần suất sự cố, nhãn ẩn.'],
 ['nextfarm_device/ml.py','Làm sạch, đặc trưng, tách dữ liệu, train, baseline, gate và inference.'],
 ['nextfarm_device/answers.py và api.py','Nhận ý định, API, điều kiện từ chối, giải thích bằng chứng và ràng buộc tủ.'],
 ['nextfarm_device/store.py và runtime.py','Phân quyền, schema device_db, MQTT và hai tình huống gián đoạn.'],
 ['nextfarm_device/automation.py','Xuất CSV tự động, điều kiện dữ liệu mới, train và registry.'],
 ['apps/device-web và apps/device-data-studio','Giao diện nông dân và dữ liệu; không có luồng tạo ticket.'],
 ['apps/knowledge-studio','Kỹ thuật viên xem và duyệt tài liệu.'],
 [str(Path(report['source_manifest']).parent.relative_to(root)),'CSV mới theo khách hàng, manifest và hash; giữ bộ trước đó riêng.'],
 ['model-artifacts/device-v11/latest_training_report.json','Bảng tổng mới nhất: nguồn, split, phương pháp, metrics và lý do gate.'],
 ['model-artifacts/device-v11/runs/'+report['dataset_version'],'training_report.json; model_summary.csv; processed_features_targets.csv; từng *_report.json, *_predictions.csv và .joblib; training_code.'],
 ['model-artifacts/device-v11/active_models.json','Chỉ các model READY và hash artifact để phục vụ dự báo.'],
 ['docs/device-v11/acceptance.json và unit-tests.xml',f'50 ca kiểm tra API và {unit_count} kiểm tra logic; không phải benchmark accuracy ML.'],
 ['docs/device-v11/synthetic_backfill_correction.json','Bản ghi trước khi sửa các payload backfill mô phỏng; không sửa dữ liệu NextFarm thật.']],[3.45,3.65])
p('docs/device-v11/export_verification.json xác nhận: tách khách train/test, purge thời gian và nạp lại cả 10 artifact để tái tạo các dự đoán test đã lưu. Mã ứng viên, seed và kết quả từng lần được giữ trong thư mục runs; kết quả không được chọn bằng việc hạ gate.')

page('Các bước tự kiểm tra và ghi báo cáo')
p('Để xem bản mới đang chạy thử, mở http://127.0.0.1:19080 và dùng tài khoản hiện có. Muốn áp dụng qua Docker, mở CMD trong thư mục dự án và chạy scripts\\start_v11.cmd. Script build, nhập bản nháp tri thức và chạy unit tests; nếu báo lỗi thì lưu đầy đủ log. Không coi cổng 18080 đã nâng cấp thành công trước khi bước build này hoàn tất.')
table(['Bước','Thao tác','Kết quả cần ghi'],[
 ['1','Đăng nhập lần lượt nongdan.long, nongdan.lan, nongdan.minh.','Mỗi người chỉ thấy đúng một tủ demo. Chụp tên tủ và customer_id.'],
 ['2','Chưa chọn tủ, thử gửi câu hỏi; sau đó chọn tủ.','Chưa chọn thì không gửi; khi chọn xong mọi câu hỏi gắn cùng device_id.'],
 ['3','Mở tab Dữ liệu, xem từng nhóm; chọn Tuần này khi Hôm nay ít bản ghi.','Ghi count, thời điểm cuối, nguồn synthetic và ID khách/tủ.'],
 ['4','Tải CSV số đo và lịch sử tưới.','Mở file kiểm tra customer_id, device_id; giá trị thiếu không bị tự thay bằng 0.'],
 ['5','Hỏi “Độ ẩm 62% có cao không?”.','Số đo cảm biến và 62% khách nhập phải phân biệt; ngưỡng demo được nói rõ.'],
 ['6','Hỏi “Dự báo EC” và “Dự báo độ ẩm không khí”.','EC được gọi khi dữ liệu đủ; độ ẩm không khí chưa có model phải từ chối dự báo.'],
 ['7','Hỏi bơm, van, lịch tưới, tổng nước, lệnh và cảnh báo.','Ghi câu hỏi, ý định, dữ liệu gốc và câu trả lời. Không thấy yêu cầu tạo ticket.'],
 ['8','Hỏi “Giá vàng ngày mai thế nào?” và “Bật bơm ngay”.','Câu ngoài phạm vi không được tạo số liệu; chat không thực hiện lệnh điều khiển.'],
 ['9','Đăng nhập kythuat.01, mở trang dữ liệu và Duyệt tri thức.','Đọc khách theo quyền, không trực chat; duyệt tài liệu DEVICE_SPEC_V11 nếu nội dung chính xác.'],
 ['10','Mở tab 10 model và 32 năng lực.',f'Ghi đúng {report["ready_count"]} model READY mô phỏng; 32 hỗ trợ là truy vấn/rule, không ghi accuracy cho chúng.']],[.5,3.2,3.4])
p('Mật khẩu dùng trong .env hiện tại; báo cáo không sao chép mật khẩu, token hoặc INTERNAL_SERVICE_KEY. Bằng chứng API trả về luôn phải kiểm tra sau đăng nhập.')

page('Kiểm tra cảnh báo và những việc còn phải hoàn thành')
p('Có thể tái chạy bộ kiểm thử API sau Docker bằng Python đã cài httpx: python scripts/check_device_acceptance.py --base http://127.0.0.1:18080 --output docs/device-v11/acceptance-docker.json --scenarios. Kịch bản chỉ dùng trong môi trường demo; script đọc khóa nội bộ từ .env và tự trả simulator về trạng thái normal.')
table(['Tình huống','Dữ liệu cần đối chiếu','Câu trả lời mong đợi'],[
 ['Mất nguồn','Giám sát độc lập power_confirmed=false, thời điểm mới; không có status/sensor mới từ tủ.','Nêu bằng chứng mất nguồn; trạng thái bơm/van cũ không phải hiện tại.'],
 ['MQTT gián đoạn','Giám sát nguồn còn, mqtt_connected=false; lịch địa phương có thể vẫn chạy.','Nêu gián đoạn truyền dữ liệu; không kết luận bơm dừng hoặc ca tưới thất bại chỉ vì mất mạng.'],
 ['Chỉ im lặng','Status cũ, không có giám sát nguồn mới.','Chưa đủ bằng chứng phân biệt mất điện và MQTT.'],
 ['Counter reset hoặc thiếu','volume_valid=false, counter_reset=true hoặc giá trị trống.','Không cộng ca này như 0; tổng hợp lệ được ghi là chưa đầy đủ.']],[1.25,2.85,3])
h('Phần chưa đạt cần trình bày thẳng',2)
p(f'1. {report["ready_count"]}/10 model READY của một bộ test mô phỏng không đồng nghĩa độ chính xác ngoài thực địa. Nếu tiếp tục sửa thiết kế sau khi đọc bảng này, phải giữ test mới độc lập cho lần đánh giá khẳng định tiếp theo.')
p('2. Chưa chứng minh hiệu quả NextFarm thực địa. Dữ liệu có 0 khách thật và 0 sự cố được xác nhận ngoài hiện trường. Cần đối chiếu các trường đo bổ sung với phần cứng/API thật và thu nhãn sự cố độc lập.')
p('3. 32 năng lực có code và dữ liệu demo để thực thi, nhưng không phải 32 AI đã học; chưa có benchmark hội thoại lớn. Sự hiểu câu hỏi hiện là quy tắc có giới hạn.')
p('4. Chưa xác nhận build Docker trong phiên này. Không dùng kết quả native_review để ghi “Docker build đã thành công”. Lưu kết quả start_v11.cmd và kiểm thử sau build làm bằng chứng riêng.')
p('5. Chưa thử tải 500 khách, chưa triển khai phân quyền Zalo OA hoặc adapter thiết bị thật. Các cấu hình production cũ không thay thế kiểm định triển khai v11.')
p('Mẫu ghi cho từng ca: thời gian chạy; tài khoản và device_id; câu hỏi; nhóm CSV/API gốc; kết quả mong đợi; kết quả quan sát; ảnh chụp; đạt/chưa đạt; nguyên nhân và file liên quan.')

path=out/'BAO-CAO-KIEM-CHUNG-THIET-BI-V11.docx';doc.save(path)
(root/'docs/DEVICE-V11-REPORT.md').write_text('\n'.join(md),encoding='utf-8')
css='body{font:16px/1.65 Arial,sans-serif;color:#15252e;max-width:1120px;margin:40px auto;padding:0 24px}h1,h2,h3{color:#000}table{border-collapse:collapse;width:100%;margin:18px 0 28px;font-size:14px}th,td{border:1px solid #d9d9d9;text-align:left;padding:10px;overflow-wrap:anywhere}th{background:#173f55;color:white}tr:nth-child(even){background:#eff4f7}h2{margin-top:48px}p{max-width:100ch}@media print{body{font-size:11pt;margin:0}h2{break-after:avoid}tr{break-inside:avoid}thead{display:table-header-group}}'
(out/'BAO-CAO-KIEM-CHUNG-THIET-BI-V11.html').write_text('<!doctype html><html lang="vi"><meta charset="utf-8"><title>Báo cáo kiểm chứng thiết bị v11</title><style>'+css+'</style><body>'+''.join(html_parts)+'</body></html>',encoding='utf-8')
print(path)
