"""Deterministic question routing and device evidence explanations."""
import re, unicodedata, math
from datetime import datetime, timezone, timedelta
from .contracts import METRICS

def norm(text):
    return ''.join(x for x in unicodedata.normalize('NFD',text.lower().replace('đ','d')) if unicodedata.category(x)!='Mn')

def contains(text,phrases):
    return any(re.search(r'\b'+re.escape(phrase)+r'\b',text) for phrase in phrases)

from .question_plan import route

def dt(value):
    if not value:return None
    try:
        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except (TypeError,ValueError):return None

def when(value):
    stamp=dt(value)
    return stamp.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M %d/%m/%Y') if stamp else 'chưa có mốc giờ'

def connectivity(status,observer=None,now=None):
    now=now or datetime.now(timezone.utc);observer=observer or {}
    timestamp=dt(status.get('observed_at'));age=(now-timestamp).total_seconds() if timestamp else None
    stale=age is None or age>30 or age < -30
    obs_at=dt(observer.get('observed_at'));obs_fresh=obs_at is not None and 0<=(now-obs_at).total_seconds()<=30
    if obs_fresh and observer.get('power_confirmed') is False:
        return {'code':'POWER_LOSS','text':'Bằng chứng giám sát nguồn xác nhận tủ mất nguồn. Tủ ngừng gửi dữ liệu; trạng thái bơm/van cuối cùng không thể coi là hiện tại. Chỉ kiểm tra đèn nguồn từ vị trí an toàn, không mở tủ điện.','evidence_source':observer.get('source')}
    if obs_fresh and observer.get('power_confirmed') is True and observer.get('mqtt_connected') is False:
        return {'code':'MQTT_INTERRUPTED','text':'Nguồn tủ vẫn được xác nhận nhưng kết nối MQTT bị gián đoạn. Có thể xem lại mạng Ethernet/WiFi/4G và trạng thái broker. Lịch giữ tại bo có thể vẫn chạy; không kết luận bơm đã dừng.','evidence_source':observer.get('source')}
    if not status:return {'code':'UNKNOWN','text':'Chưa nhận được trạng thái tủ. Chưa đủ bằng chứng phân biệt mất nguồn và lỗi kết nối.'}
    if stale:return {'code':'UNKNOWN','text':f'Dữ liệu trạng thái đã bị trễ; lần cuối lúc {when(status.get("observed_at"))}. Chưa đủ bằng chứng kết luận mất điện hay lỗi MQTT. Hãy kiểm tra chỉ báo nguồn và mạng của tủ.'}
    if status.get('online') is False:return {'code':'UNKNOWN','text':f'Bản ghi lúc {when(status.get("observed_at"))} báo thiết bị offline. Chưa có bằng chứng đủ mới để phân biệt mất nguồn và lỗi MQTT; không coi trạng thái bơm/van là hiện tại.'}
    return {'code':'CONNECTED','text':f'Tủ còn gửi trạng thái, lần gần nhất lúc {when(status.get("observed_at"))}.'}

def fertilizer_reasons(status):
    checks=[('valve_running','chưa có van vùng mở'),('pump_running','relay bơm nước chưa chạy'),
            ('fertilizer_requested','chưa có kênh phân được gọi'),('dosage_configured','chưa cấu hình định lượng')]
    reasons=[label if status.get(key) is False or status.get(key)==0 else 'chưa có dữ liệu xác nhận: '+label for key,label in checks if not status.get(key)]
    calibrated=status.get('calibration_valid') is True and isinstance(status.get('calibrated_ml_per_min'),(float,int)) and status['calibrated_ml_per_min']>0
    if not status.get('meter_configured') and not calibrated:reasons.append('chưa có đồng hồ hoặc hệ số hiệu chỉnh được xác nhận')
    if status.get('emergency_stop'):reasons.insert(0,'nút dừng khẩn hoặc khóa an toàn đang chốt')
    if status.get('fertilizer_stop_latched'):reasons.insert(0,'khóa bơm phân đã chốt; cần lệnh mới sau khi kiểm tra đủ điều kiện')
    return reasons

def sensor_answer(data,metric,message,profile,now=None):
    now=now or datetime.now(timezone.utc);rows=data.get('items',[])
    if not metric:return 'Hãy chọn chỉ số cần hỏi hoặc tên cảm biến.'
    name,unit=METRICS[metric];row=next((x for x in reversed(rows) if x.get(metric) is not None),None)
    if not row:return f'Tủ đang chọn chưa có số đo {name}. Tôi không suy ra giá trị thay thế.'
    value=row[metric];stamp=dt(row.get('observed_at'));age=(now-stamp).total_seconds() if stamp else 1e9
    from .collection import SIGNALS
    try:
        value=float(value)
        if not math.isfinite(value) or (metric in SIGNALS and not SIGNALS[metric][0]<=value<=SIGNALS[metric][1]):raise ValueError()
    except (ValueError,TypeError):return f'Số đo {name} không hợp lệ; chưa thể đưa ra giá trị hay đánh giá cao/thấp.'
    text=f'{name.capitalize()} đo được {float(value):.3f} {unit} lúc {when(row.get("observed_at"))}.'
    if age < -30:return 'Mốc giờ cảm biến nằm trong tương lai; chưa dùng số đo này để kết luận.'
    if age>1800:return text+' Dữ liệu đã bị trễ; không dùng để kết luận hiện tại.'
    if row.get('quality') in ['bad','suspect']:return text+' Chất lượng cảm biến bị nghi ngờ; chưa dùng để đánh giá.'
    # Explicit values in questions are hypothetical/user-reported, never silently overwrite telemetry.
    value_match=re.search(r'(\d+(?:[.,]\d+)?)\s*(%|°c|ms/cm|ph\b)',message,re.I)
    compare=float(value_match.group(1).replace(',','.')) if value_match else float(value)
    if value_match:text+=f' Với giá trị bạn nhập {compare:g} {unit} (chưa xác minh bằng cảm biến):'
    bounds=profile.get('thresholds',{}).get(metric)
    if bounds:
        lo,hi=bounds;level='low' if compare<lo else 'high' if compare>hi else 'good'
        label={'low':'thấp hơn','high':'cao hơn','good':'trong'}[level]
        text+=f' Giá trị ở {label} ngưỡng đã cấu hình {lo}–{hi} {unit} cho vườn này.'
        crop=profile.get('crop') or 'cây trồng'
        effects={
          'temperature':{
            'low':f'Nhiệt độ thấp kéo dài có thể làm {crop} sinh trưởng chậm hơn.',
            'good':f'Theo ngưỡng đang cài đặt, mức này thuận lợi để {crop} duy trì hoạt động sinh lý bình thường.',
            'high':f'Nhiệt độ cao kéo dài có thể làm {crop} thoát hơi nước mạnh và tăng nguy cơ stress nhiệt.'},
          'soil_moisture':{
            'low':f'Đất đang khô hơn mức cài đặt; {crop} có thể khó hút đủ nước nếu tình trạng kéo dài.',
            'good':f'Theo ngưỡng đang cài đặt, độ ẩm này thuận lợi để vùng rễ {crop} duy trì nước ổn định.',
            'high':f'Đất ẩm hơn mức cài đặt; nếu kéo dài, vùng rễ {crop} có thể thiếu thoáng khí.'},
          'ec':{
            'low':'EC thấp hơn mức cài đặt có thể phản ánh nồng độ dinh dưỡng còn thấp.',
            'good':'Theo ngưỡng đang cài đặt, EC hiện tại nằm trong khoảng dinh dưỡng tham chiếu của vườn.',
            'high':'EC cao hơn mức cài đặt có thể làm cây khó hút nước do nồng độ muối cao.'},
          'ph':{
            'low':'pH thấp hơn mức cài đặt có thể ảnh hưởng khả năng hấp thu một số dinh dưỡng.',
            'good':'Theo ngưỡng đang cài đặt, pH hiện tại thuận lợi hơn cho việc hấp thu dinh dưỡng.',
            'high':'pH cao hơn mức cài đặt có thể làm một số dinh dưỡng khó được cây hấp thu.'}}
        if metric in effects:text+=' '+effects[metric][level]
        if not profile.get('agronomy_approved',False):text+=' Đây là đánh giá theo ngưỡng cấu hình tham chiếu; chưa thay thế tư vấn chuyên gia theo giống cây và giai đoạn sinh trưởng.'
    else:text+=' Vườn chưa có ngưỡng được cấu hình cho chỉ số này, nên chưa xếp cao/thấp.'
    text+=' Số đo cảm biến có sai số; đánh giá cao/thấp dựa trên khoảng ngưỡng và nên đối chiếu nhiều điểm đo liên tiếp, không kết luận tuyệt đối từ một lần đo.'
    return text

def render_tool(tool,data,plan,message,profile,observer=None,now=None):
    rows=data.get('items',[]);last=rows[-1] if rows else {};metric=plan.get('metric')
    zone=plan.get('zone_id')
    if zone and tool in ['sensor','sensor_history','irrigation','schedules','operation']:
        configured={x.get('zone_id') for x in profile.get('zones',[])}
        if configured and zone not in configured:return f'Tủ đang chọn chưa cấu hình khu {zone.removeprefix("zone_").upper()}. Hãy chọn đúng tủ hoặc kiểm tra cấu hình khu; chưa có dữ liệu để trả lời khu này.'
        if tool!='operation':
            rows=[r for r in rows if r.get('zone_id')==zone];data={**data,'items':rows};last=rows[-1] if rows else {}
            if 'previous_items' in data:data['previous_items']=[r for r in data['previous_items'] if r.get('zone_id')==zone]
            if not rows:return 'Chưa có bản ghi gắn đúng khu được hỏi trong kỳ. Tôi không lấy số liệu khu khác để thay thế.'
    if tool=='sensor':return sensor_answer(data,metric,message,profile,now)
    if tool=='sensor_quality':
        if not rows:return 'Chưa có bản ghi cảm biến để kiểm tra chất lượng.'
        missing=[METRICS[k][0] for k in ['soil_moisture','temperature','ec','ph','flow_rate'] if last.get(k) is None]
        return f'Bản ghi lúc {when(last.get("observed_at"))}: chất lượng {last.get("quality","chưa xác nhận")}. Thiếu: '+(', '.join(missing) if missing else 'không thiếu các chỉ số cơ bản')+'. Giá trị thiếu được giữ trống, không thay bằng 0.'
    if tool=='sensor_history':
        vals=[float(x[metric]) for x in rows if metric and x.get(metric) is not None and x.get('quality') not in ['bad','suspect']]
        if not vals:return 'Chưa có chuỗi số đo đạt chất lượng trong khoảng đã chọn.'
        name,unit=METRICS[metric]
        if plan.get('operation') in ['max','min']:
            value=max(vals) if plan['operation']=='max' else min(vals)
            label='cao nhất' if plan['operation']=='max' else 'thấp nhất'
            row=next(x for x in rows if x.get(metric) is not None and float(x[metric])==value)
            return f'{name.capitalize()} {label} {value:.3f} {unit} lúc {when(row.get("observed_at"))}. Kết quả chỉ phản ánh các bản ghi hợp lệ trong khoảng được hỏi; cảm biến có sai số.'
        return f'{name.capitalize()}: {len(vals)} điểm hợp lệ, trung bình {sum(vals)/len(vals):.3f} {unit}, thấp nhất {min(vals):.3f}, cao nhất {max(vals):.3f}; thay đổi đầu-cuối {vals[-1]-vals[0]:+.3f} {unit}. Khoảng {when(rows[0].get("observed_at"))} đến {when(last.get("observed_at"))}. Đây là mô tả chuỗi đã đo; cảm biến có sai số và không kết luận tuyệt đối từ một điểm đo.'
    if tool=='connection':return connectivity(last,observer,now)['text']
    if tool=='operation':
        connection=connectivity(last,observer,now)
        if connection['code']!='CONNECTED':return connection['text']
        if zone and plan.get('port') is None:
            output=next((x for x in last.get('outputs',[]) if x.get('zone_id')==zone and x.get('role')=='zone_valve'),None)
            if not output:return 'Chưa có trạng thái van gắn đúng khu được hỏi; không suy từ trạng thái van chung.'
            plan={**plan,'port':output['port']}
        if plan.get('port') is not None:
            port=plan['port'];output=next((x for x in last.get('outputs',[]) if x.get('port')==port),None)
            if not output:return f'Chưa có trạng thái ngõ ra số {port}; không suy từ trạng thái bơm/van chung.'
            role=output.get('role','chưa cấu hình vai trò');role_vi={'water_pump':'bơm nước','zone_valve':'van vùng','fertilizer_pump':'bơm phân','fertilizer_valve':'van phân'}.get(role,role)
            if zone and output.get('zone_id')!=zone:return 'Ngõ ra được hỏi chưa được ánh xạ đúng khu này; cần kiểm tra cấu hình.'
            prefix=f'Ngõ ra số {port} được cấu hình là {role_vi}'
            if plan.get('requested_role')=='van' and 'van' not in role_vi:prefix+='; số này không được cấu hình là van'
            running=output.get('running');return prefix+f'; trạng thái {"chưa rõ" if running is None else "đang chạy/mở" if running else "đang dừng/đóng"}, lúc {when(last.get("observed_at"))}.'
        outputs=last.get('outputs',[])
        if plan.get('operation')=='count_open' or contains(norm(message),['bao nhieu van','may van']):
            valves=[x for x in outputs if x.get('role') in ['zone_valve','fertilizer_valve'] and x.get('running') is True]
            names=', '.join(f'van {x.get("port")}' for x in valves) or 'không có van nào'
            return f'Hiện tại có {len(valves)} van đang mở: {names}, theo trạng thái lúc {when(last.get("observed_at"))}.'
        reasons=fertilizer_reasons(last)
        state=lambda k:'chưa rõ' if last.get(k) is None else 'đang chạy/mở' if last[k] else 'đang dừng/đóng'
        result=f'Bơm nước {state("pump_running")}; van vùng {state("valve_running")}; bơm phân {state("fertilizer_running")}, lúc {when(last.get("observed_at"))}.'
        explain_fertilizer=plan.get('operation')=='reason' or contains(norm(message),['cham phan','bon phan','bom phan','chua bon','khong bon'])
        if reasons and explain_fertilizer:
            result+=' Bơm phân chưa được phép chạy vì: '+ '; '.join(reasons)+'. Hãy kiểm tra lịch có gọi đúng khu, định lượng và khóa an toàn; sau dừng khẩn hệ thống không tự chạy lại.'
        elif explain_fertilizer and last.get('fertilizer_running') is not True:
            result+=' Các điều kiện có trong bản ghi đều đã thỏa nhưng chưa thấy bơm phân chạy; hãy đối chiếu nhật ký lệnh và trạng thái cổng ra, không tự bỏ qua khóa an toàn.'
        return result
    if tool=='schedules':return 'Chưa có lịch tưới trong cấu hình tủ.' if not rows else 'Lịch đang lưu tại tủ: '+'; '.join(f'{x.get("name", "Lịch")}, {x.get("start_time", "mỗi "+str(x.get("every_hours","?"))+" giờ")}, {x.get("duration_minutes","?")} phút' for x in rows)+'. Lịch tại bo có thể tiếp tục khi mất mạng; cần nhật ký để xác nhận đã chạy.'
    if tool=='irrigation':
        if not rows:return 'Không có ca tưới được ghi nhận trong kỳ. Không đồng nghĩa ngoài hiện trường chắc chắn chưa tưới khi mất kết nối.'
        valid=lambda r,k:r.get(k) is not None and not r.get('counter_reset') and r.get('volume_valid',True)
        water=sum(float(x['water_liters']) for x in rows if valid(x,'water_liters'));fert=sum(float(x['fertilizer_ml']) for x in rows if valid(x,'fertilizer_ml'))
        unknown=sum(not valid(x,'water_liters') or not valid(x,'fertilizer_ml') for x in rows)
        period_vi={'today':'hôm nay','yesterday':'hôm qua','week':'tuần này','last_week':'tuần trước','month':'tháng này','last_month':'tháng trước'}.get(plan['period'],plan['period'])
        fields=plan.get('requested_fields',[])
        if plan.get('operation')=='list':
            lines=[]
            for idx,x in enumerate(rows,1):
                parts=[]
                if not fields or 'start_time' in fields: parts.append('bắt đầu '+when(x.get('started_at')))
                if not fields or 'end_time' in fields: parts.append('kết thúc '+when(x.get('ended_at')))
                if not fields or 'water_liters' in fields: parts.append(f'nước {float(x.get("water_liters")):.2f} L' if valid(x,'water_liters') else 'nước chưa đo hợp lệ')
                if not fields or 'fertilizer_ml' in fields: parts.append(f'phân {float(x.get("fertilizer_ml")):.2f} mL' if valid(x,'fertilizer_ml') else 'phân chưa đo hợp lệ')
                if 'duration_minutes' in fields:
                    parts.append(f'thời lượng {((dt(x["ended_at"])-dt(x["started_at"])).total_seconds()/60):.1f} phút' if x.get('started_at') and x.get('ended_at') else 'thời lượng chưa đủ mốc')
                lines.append(f'{idx}. '+'; '.join(parts))
            return f'Các ca tưới {period_vi} ({len(rows)} ca):\n'+'\n'.join(lines)
        result=f'Trong kỳ {period_vi} ghi nhận {len(rows)} ca tưới; cộng phần có số đo hợp lệ: nước {water:.2f} L; phân {fert:.2f} mL. Dữ liệu cuối lúc {when(last.get("observed_at",last.get("ended_at")))}.'
        if unknown:result+=f' Có {unknown} ca thiếu số đo/đếm không hợp lệ; các tổng trên chưa đầy đủ, không xem thiếu là 0.'
        channels={str(x.get('fertilizer_channel','chưa rõ')) for x in rows}
        result+=' Theo kênh phân: '+ '; '.join(f'{c}: {sum(float(x["fertilizer_ml"]) for x in rows if str(x.get("fertilizer_channel","chưa rõ"))==c and valid(x,"fertilizer_ml")):.2f} mL' for c in sorted(channels))+'.'
        durations=[(dt(x['ended_at'])-dt(x['started_at'])).total_seconds()/60 for x in rows if x.get('ended_at') and x.get('started_at')]
        durations=[n for n in durations if n>=0]
        if durations:result+=f' Tổng thời lượng ghi nhận {sum(durations):.1f} phút, trung bình {sum(durations)/len(durations):.1f} phút trên {len(durations)} ca có đủ mốc giờ.'
        if len(durations)!=len(rows):result+=' Có ca thiếu hoặc sai mốc giờ; tổng thời lượng chưa đầy đủ.'
        if any(x in norm(message) for x in ['ngay nao khong tuoi','ngay nao chua tuoi']):
            from .store import period_bounds
            start,end=period_bounds(plan['period']);day=start.date();days=[];tz=timezone(timedelta(hours=7))
            covered={dt(x.get('started_at',x.get('observed_at'))).astimezone(tz).date() for x in rows if x.get('started_at',x.get('observed_at'))}
            while day<=end.astimezone(tz).date():
                if day not in covered:days.append(day.strftime('%d/%m'))
                day+=timedelta(days=1)
            result+=' Ngày chưa có ca ghi nhận: '+(', '.join(days) if days else 'không có trong khoảng đã tra')+'. Không có bản ghi không chứng minh ngoài thực tế chưa tưới; cần đối chiếu nhật ký tại tủ, độ phủ kết nối và thời gian bắt đầu thu dữ liệu.'
        outcomes={str(x.get('result','chưa rõ')) for x in rows}
        result+=' Kết quả ca: '+ '; '.join(f'{k}: {sum(str(x.get("result","chưa rõ"))==k for x in rows)}' for k in sorted(outcomes))+'.'
        prev=data.get('previous_items')
        if prev is not None:result+=f' Kỳ trước có {len(prev)} ca, phần đo hợp lệ {sum(float(x["water_liters"]) for x in prev if valid(x,"water_liters")):.2f} L nước; {sum(not valid(x,"water_liters") for x in prev)} ca thiếu số đo.'
        return result+' Thống kê tính ca kết thúc trong kỳ; ca còn chạy chưa nằm trong tổng. Dữ liệu thiếu hoặc chưa đồng bộ có thể làm tổng thấp hơn thực tế.'
    if tool=='commands':return 'Chưa có nhật ký lệnh trong kỳ.' if not rows else f'Ghi nhận {len(rows)} lệnh, {sum(x.get("status") in ["failed","rejected","timeout"] for x in rows)} lệnh báo thất bại. Nhật ký gần nhất: '+'; '.join(f'{x.get("requested_by","không rõ người gửi")} gửi {x.get("command","lệnh")} lúc {when(x.get("observed_at",x.get("requested_at")))}: {x.get("status","chưa xác nhận")}' for x in rows[-5:])+'. Lệnh đã gửi không chứng minh relay đã chạy.'
    if tool=='alerts':return 'Không có cảnh báo ghi nhận trong kỳ; xem trạng thái kết nối để biết dữ liệu có còn mới.' if not rows else 'Cảnh báo: '+'; '.join(x.get('text',x.get('code','chưa rõ')) for x in rows[-5:])
    if tool=='profile':return f'Tủ {profile.get("device_name",profile.get("device_id"))}, phần cứng {profile.get("model","ESP32-S3")}; cảm biến và ngõ ra được liệt kê trong bảng dữ liệu. '+str(profile.get('outputs',[]))
    return 'Chưa có công cụ phù hợp cho câu hỏi này. Bạn có thể hỏi số đo, kết nối tủ, bơm/van, lịch tưới, nước/phân hoặc nhật ký lệnh.'
