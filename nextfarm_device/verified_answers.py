"""Exact query facts from scoped evidence; missing != zero, stale != current."""
import math
from decimal import Decimal,InvalidOperation
from datetime import datetime,timezone,timedelta
from .contracts import METRICS
from .question_plan import norm,has

def timestamp(value):
    try:
        d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (TypeError,ValueError):return None

def number(value,lo=None,hi=None):
    if isinstance(value,bool):return None
    try:
        d=Decimal(str(value))
        if not d.is_finite() or (lo is not None and d<lo) or (hi is not None and d>hi):return None
        return d
    except (TypeError,ValueError,InvalidOperation):return None

def flag(value):
    if value is True or value==1 or str(value).lower()=='true':return True
    if value is False or value==0 or str(value).lower()=='false':return False
    return None

def display_time(value):
    d=timestamp(value)
    return d.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M %d/%m/%Y') if d else 'chưa có mốc giờ hợp lệ'

def float_or_none(value):return float(value) if value is not None else None
def fmt(value,digits=2):return f'{value:.{digits}f}' if value is not None else 'chưa xác định'
def result(text,facts=None,status='answered'):return {'text':text,'facts':facts or {},'status':status}
def row_time(row):return timestamp(row.get('observed_at') or row.get('ended_at') or row.get('requested_at')) or datetime.min.replace(tzinfo=timezone.utc)

def answer(tool,data,plan,message,profile,observer=None,now=None):
    now=now or datetime.now(timezone.utc);rows=sorted(data.get('items',[]),key=row_time);op=plan.get('operation','summary');text=norm(message)
    if data.get('truncated'):return result('Dữ liệu trả về chưa đủ toàn bộ kỳ. Hãy chọn khoảng thời gian ngắn hơn; chưa tính tổng từ phần bị cắt.',status='partial')
    zone=plan.get('zone_id')
    if zone:
        known={z.get('zone_id') for z in profile.get('zones',[])}
        if known and zone not in known:return result(f'Tủ đang chọn chưa cấu hình khu {zone.removeprefix("zone_").upper()}. Tôi không dùng số liệu khu khác.',status='no_data')
        if tool in ['sensor','sensor_quality','sensor_history','irrigation','schedules','alerts','commands']:rows=[r for r in rows if r.get('zone_id')==zone]
    if not zone and tool in ['sensor','sensor_quality','sensor_history'] and op!='compare_zones':
        zones=sorted({r.get('zone_id') for r in rows if r.get('zone_id')})
        if len(zones)>1:
            parts={z:answer(tool,{**data,'items':rows},{**plan,'zone_id':z},message,profile,observer,now) for z in zones}
            return result(' '.join(z.removeprefix('zone_').upper()+': '+p['text'] for z,p in parts.items()),{'zones':{z:p['facts'] for z,p in parts.items()}},'answered' if all(p['status']=='answered' for p in parts.values()) else 'partial')
    if tool=='profile':
        fields={'crop':profile.get('crop'),'area_m2':profile.get('area_m2'),'device_model':profile.get('model'),
          'installed_sensors':profile.get('installed_sensors'),'thresholds':profile.get('thresholds'),
          'zones':profile.get('zones'),'outputs':profile.get('outputs'),'fertilizer_channels':profile.get('fertilizer_channels')}
        if has(text,'dien tich'):
            area=next((z.get('area_m2') for z in profile.get('zones',[]) if z.get('zone_id')==zone),None) if zone else fields['area_m2']
            return result('Diện tích đã khai báo: '+(fmt(number(area,0))+' m².' if number(area,0) is not None else 'chưa có dữ liệu.'),{'area_m2':float_or_none(number(area,0))},'answered' if number(area,0) is not None else 'no_data')
        if has(text,'trong cay'):return result('Cây trồng đã khai báo: '+str(fields['crop'] or 'chưa có dữ liệu')+'.',{'crop':fields['crop']},'answered' if fields['crop'] else 'no_data')
        if has(text,'nguong'):
            metric=plan.get('metric');bounds=(fields['thresholds'] or {}).get(metric)
            return result(f'Ngưỡng cấu hình {METRICS.get(metric,(metric,""))[0]}: '+(str(bounds)+'.' if bounds else 'chưa khai báo.')+' Đây là ngưỡng cài đặt; chưa tự suy ra khuyến nghị tưới cho cây.',{'metric':metric,'configured_threshold':bounds},'answered' if bounds else 'no_data')
        if has(text,'noi voi','van so may'):
            z=next((z for z in profile.get('zones',[]) if z.get('zone_id')==zone),{})
            return result('Khu được hỏi gắn với van/ngõ ra số '+str(z.get('valve_port','chưa khai báo'))+'.',{'zone_id':zone,'valve_port':z.get('valve_port')},'answered' if z.get('valve_port') is not None else 'no_data')
        labels={'crop':'Cây trồng','area_m2':'Diện tích (m²)','device_model':'Loại tủ','installed_sensors':'Cảm biến lắp đặt','thresholds':'Ngưỡng cấu hình','zones':'Các khu','outputs':'Ngõ ra','fertilizer_channels':'Kênh phân'}
        return result('Hồ sơ đã khai báo: '+'; '.join(labels[k]+': '+str(v if v is not None else 'chưa có dữ liệu') for k,v in fields.items())+'.',fields)
    if tool in ['sensor','sensor_history','sensor_quality']:
        selected=plan.get('metrics') or ([plan['metric']] if plan.get('metric') else ['soil_moisture','temperature','air_humidity','ec','ph','flow_rate'])
        if not rows:return result('Chưa có số đo đúng khu/kỳ được hỏi; tôi không suy ra số liệu thay thế.',status='no_data')
        from .collection import SIGNALS
        facts={};lines=[];partial=False
        if op=='compare_zones':
            latest={}
            for r in rows:latest[r.get('zone_id','chưa gắn khu')]=r
            rows=list(latest.values())
        for metric in selected:
            unit=METRICS.get(metric,(metric,''))[1];label=METRICS.get(metric,(metric,''))[0]
            lo,hi=SIGNALS.get(metric,(-1e9,1e9));valid=[]
            for r in rows:
                v=number(r.get(metric),lo,hi);t=timestamp(r.get('observed_at'))
                if v is not None and t and t<=now+timedelta(seconds=30) and r.get('quality') not in ['bad','suspect']:
                    valid.append((r,v,t))
            if tool=='sensor_quality':
                latest=rows[-1];facts[metric]={'valid':any(x[0] is latest for x in valid),'quality':latest.get('quality'),'observed_at':latest.get('observed_at')}
                lines.append(label+': '+('hợp lệ' if facts[metric]['valid'] else 'thiếu/không hợp lệ'))
                continue
            if tool=='sensor':
                # Do not hide a newer invalid reading by presenting an older value as current.
                latest=rows[-1];found=next((v for r,v,t in valid if r is latest),None)
                if found is None:
                    facts[metric]={'value':None,'observed_at':latest.get('observed_at')};lines.append(label+': số đo mới nhất thiếu hoặc không hợp lệ.');partial=True;continue
                age=(now-timestamp(latest['observed_at'])).total_seconds();stale=age>1800
                facts[metric]={'value':float(found),'unit':unit,'observed_at':latest['observed_at'],'stale':stale,'source':'measurement'}
                line=f'{label.capitalize()}: {found:.3f} {unit}, lúc {display_time(latest["observed_at"])}.'
                if stale:line+=' Dữ liệu đã trễ; không dùng để kết luận hiện tại.';partial=True
                else:
                    from .answers import sensor_answer
                    line=sensor_answer({'items':[latest]},metric,message,profile,now)
                lines.append(line);continue
            if not valid:lines.append(label+': chưa có số đo hợp lệ trong kỳ.');facts[metric]={'count':0};partial=True;continue
            values=[v for _,v,_ in valid];low=min(valid,key=lambda x:x[1]);high=max(valid,key=lambda x:x[1]);mean=sum(values)/len(values)
            entry={'count':len(values),'mean':float(mean),'min':float(low[1]),'max':float(high[1]),'min_at':low[0]['observed_at'],'max_at':high[0]['observed_at'],
              'first':float(values[0]),'last':float(values[-1]),'change':float(values[-1]-values[0]),'unit':unit,'excluded':len(rows)-len(valid)}
            if op=='compare_zones':
                entry['lowest_zone']=low[0].get('zone_id');entry['highest_zone']=high[0].get('zone_id')
                lines.append(f'{label}: khu thấp nhất {entry["lowest_zone"]} = {low[1]:.3f} {unit}, lúc {display_time(low[0]["observed_at"])}; so sánh các số đo mới nhất đã nhận của từng khu.')
            else:lines.append(f'{label}: {len(values)} số đo hợp lệ; trung bình {mean:.3f} {unit}; thấp nhất {low[1]:.3f} lúc {display_time(low[0]["observed_at"])}; cao nhất {high[1]:.3f} lúc {display_time(high[0]["observed_at"])}; thay đổi đầu-cuối {values[-1]-values[0]:+.3f} {unit}.')
            if entry['excluded']:lines.append(f'Có {entry["excluded"]} bản ghi thiếu/không hợp lệ bị loại khỏi thống kê.');partial=True
            if data.get('previous_items') is not None:
                previous=[number(r.get(metric),lo,hi) for r in data['previous_items'] if r.get('quality') not in ['bad','suspect'] and (not zone or r.get('zone_id')==zone) and timestamp(r.get('observed_at')) and timestamp(r.get('observed_at'))<=now+timedelta(seconds=30)]
                previous=[v for v in previous if v is not None];entry['previous_mean']=float(sum(previous)/len(previous)) if previous else None
                entry['mean_difference']=float(mean-Decimal(str(entry['previous_mean']))) if previous else None
                lines.append('Trung bình kỳ đối chiếu: '+fmt(entry['previous_mean'],3)+f' {unit}; chênh lệch trung bình: '+fmt(entry['mean_difference'],3)+f' {unit}.')
                if not previous:partial=True
            facts[metric]=entry
        return result(' '.join(lines),facts,'partial' if partial else 'answered')
    if tool=='irrigation':
        if not rows:return result('Không có ca tưới được ghi nhận trong kỳ. Không đồng nghĩa ngoài hiện trường chắc chắn chưa tưới; có thể thiếu dữ liệu hoặc mất kết nối.',{'run_count':0},'no_data')
        def completed(r):
            end=timestamp(r.get('ended_at'));start=timestamp(r.get('started_at'))
            return end is not None and end<=now and (start is None or start<=end)
        excluded_runs=sum(not completed(r) for r in rows);rows=[r for r in rows if completed(r)]
        if not rows:return result('Chưa có ca có mốc kết thúc hợp lệ. Ca đang chạy, mốc giờ sai hoặc nằm trong tương lai chưa được cộng vào tổng.',{'run_count':0,'excluded_incomplete_or_invalid_runs':excluded_runs,'water_liters':None},'no_data')
        if op=='last':rows=[max(rows,key=lambda r:timestamp(r.get('ended_at')) or row_time(r))]
        filtered=rows
        if op in ['success','failed']:filtered=[r for r in rows if r.get('result') in (['success','completed'] if op=='success' else ['failed','aborted','failure'])]
        channel=__import__('re').search(r'\b(?:bon phan|kenh phan|bon)\s+(?:so\s+)?(\d+)\b',text)
        if channel:
            # Runtime channels are zero-based; user-facing channels start at one.
            idx=int(channel.group(1))-1;filtered=[r for r in filtered if r.get('fertilizer_channel')==idx]
        if not filtered:return result('Chưa có ca tưới phù hợp điều kiện được hỏi; không suy ra lượng nước bằng 0.',{'run_count':0,'water_liters':None,'fertilizer_ml':None},'no_data')
        def amounts(key,items):
            pairs=[(r,number(r.get(key),0)) for r in items]
            valid=[(r,v) for r,v in pairs if v is not None and flag(r.get('counter_reset')) is not True and flag(r.get('volume_valid')) is not False]
            return sum((v for r,v in valid),Decimal(0)) if valid else None,valid
        water,wv=amounts('water_liters',filtered);fert,fv=amounts('fertilizer_ml',filtered)
        durations=[]
        for r in filtered:
            start,end=timestamp(r.get('started_at')),timestamp(r.get('ended_at'))
            if start and end and start<=end<=now:durations.append(Decimal(str((end-start).total_seconds()))/60)
        total=sum(durations) if durations else None
        facts={'run_count':len(filtered),'excluded_incomplete_or_invalid_runs':excluded_runs,'water_liters':float_or_none(water),'water_missing_count':len(filtered)-len(wv),
          'fertilizer_ml':float_or_none(fert),'fertilizer_missing_count':len(filtered)-len(fv),'duration_minutes':float_or_none(total),
          'duration_missing_count':len(filtered)-len(durations),'mean_duration_minutes':float_or_none(total/len(durations) if durations else None),
          'mean_water_liters':float_or_none(water/len(wv) if wv else None),
          'success_count':sum(r.get('result') in ['success','completed'] for r in filtered),'failed_count':sum(r.get('result') in ['failed','failure','aborted'] for r in filtered)}
        words=f'Ghi nhận {len(filtered)} ca tưới phù hợp; lượng nước đo hợp lệ {fmt(water)} L; phân đo hợp lệ {fmt(fert)} mL. Tổng thời lượng có đủ mốc giờ {fmt(total,1)} phút; trung bình {fmt(facts["mean_duration_minutes"],1)} phút/ca. Trung bình nước {fmt(facts["mean_water_liters"])} L/ca có số đo.'
        if has(text,'met khoi','m3'):
            facts['water_m3']=float_or_none(water/1000 if water is not None else None);words+=f' Quy đổi: {fmt(facts["water_m3"],4)} m³.'
        if op in ['last','max','min'] and filtered:
            selected=filtered[-1] if op=='last' else ((max if op=='max' else min)(wv,key=lambda p:p[1])[0] if wv else None)
            if selected:
                facts['selected_run']={k:selected.get(k) for k in ['run_id','event_id','started_at','ended_at','water_liters','result']}
                words+=' Ca được hỏi: bắt đầu '+display_time(selected.get('started_at'))+', kết thúc '+display_time(selected.get('ended_at'))+', lượng nước '+fmt(number(selected.get('water_liters'),0))+' L.'
        if op=='compare':
            previous=[r for r in data.get('previous_items',[]) if (not zone or r.get('zone_id')==zone) and completed(r)];pw,pv=amounts('water_liters',previous)
            facts['previous_water_liters']=float_or_none(pw);facts['water_difference_liters']=float_or_none(water-pw if water is not None and pw is not None else None)
            words+=f' Kỳ đối chiếu có {len(previous)} ca; nước đo hợp lệ {fmt(pw)} L; chênh lệch {fmt(facts["water_difference_liters"])} L.'
            if len(pv)!=len(previous) or not previous:words+=' Kỳ đối chiếu chưa đầy đủ nên chưa kết luận tăng/giảm tổng thực tế.'
        partial=any(facts[k]>0 for k in ['water_missing_count','fertilizer_missing_count','duration_missing_count'])
        if excluded_runs:words+=f' Đã loại {excluded_runs} ca chưa có mốc kết thúc hợp lệ khỏi tổng.';partial=True
        if op=='compare' and (not previous or len(pv)!=len(previous)):partial=True
        if has(text,'ngay nao chua tuoi','ngay nao khong tuoi'):
            from .store import period_bounds
            start,end=period_bounds(plan.get('period','today'),now);tz=timezone(timedelta(hours=7))
            day=start.astimezone(tz).date();end_day=(end-timedelta(microseconds=1)).astimezone(tz).date()
            covered={timestamp(r['ended_at']).astimezone(tz).date() for r in rows if timestamp(r.get('ended_at'))};missing=[]
            while day<=end_day:
                if day not in covered:missing.append(day.isoformat())
                day+=timedelta(days=1)
            facts['days_without_completed_run_log']=missing
            words+=' Ngày chưa có ca hoàn tất được ghi nhận: '+(', '.join(missing) if missing else 'không có trong khoảng đã tra')+'. Điều này không chứng minh ngoài hiện trường chưa tưới.'
        if op=='quality':
            valid_ids={id(r) for r,v in wv};facts['invalid_water_run_ids']=[r.get('run_id',r.get('event_id')) for r in filtered if id(r) not in valid_ids]
            words+=' Mã ca thiếu/sai số đo nước: '+str(facts['invalid_water_run_ids'])+'.'
        if partial:words+=f' Có {facts["water_missing_count"]} ca thiếu/không hợp lệ về nước, {facts["fertilizer_missing_count"]} ca về phân và {facts["duration_missing_count"]} ca về thời gian. Tổng chưa đầy đủ; không xem thiếu là 0.'
        words+=f' Kết quả ghi nhận: {facts["success_count"]} thành công, {facts["failed_count"]} thất bại. Thống kê ca kết thúc trong kỳ; ca còn chạy và dữ liệu chưa đồng bộ có thể chưa nằm trong tổng.'
        return result(words,facts,'partial' if partial else 'answered')
    if tool=='schedules':
        if op in ['enabled','disabled']:rows=[r for r in rows if flag(r.get('enabled')) is (op=='enabled')]
        if not rows:return result('Chưa có cấu hình lịch tưới phù hợp được ghi nhận; không suy ra số ca đã hoặc sẽ thực sự chạy.',{'schedule_count':0},'no_data')
        facts={'schedule_count':len(rows),'schedules':[{k:r.get(k) for k in ['name','start_time','every_hours','duration_minutes','enabled','zone_id']} for r in rows]}
        words=[f'Có {len(rows)} cấu hình lịch phù hợp:']
        for r in rows:
            time='lúc '+str(r['start_time']) if r.get('start_time') else 'chu kỳ mỗi '+str(r['every_hours'])+' giờ (chưa có mốc bắt đầu để suy ra giờ cụ thể)' if r.get('every_hours') else 'chưa có giờ bắt đầu'
            enabled=flag(r.get('enabled'));state='đang bật' if enabled is True else 'đang tắt' if enabled is False else 'chưa có cờ bật/tắt'
            words.append(str(r.get('name','Lịch chưa có tên'))+': '+time+', '+fmt(number(r.get('duration_minutes'),0),1)+' phút, '+state+'.')
        return result(' '.join(words)+' Đây là cấu hình lịch, không xác nhận ca đã chạy. Lịch tại bo có thể tiếp tục khi mất mạng; cần nhật ký để xác nhận.',facts)
    if tool=='commands':
        if op=='last' and rows:rows=rows[-1:]
        if op=='failed':rows=[r for r in rows if r.get('status') in ['failed','rejected','timeout']]
        if op=='pending':rows=[r for r in rows if r.get('status') in ['pending','sent','queued','awaiting_ack']]
        facts={'command_count':len(rows),'failed_count':sum(r.get('status') in ['failed','rejected','timeout'] for r in rows),
          'latest':{k:rows[-1].get(k) for k in ['command','requested_by','status','observed_at']} if rows else None}
        detail='; '.join(str(r.get('requested_by','chưa rõ người gửi'))+' gửi '+str(r.get('command','chưa rõ lệnh'))+' lúc '+display_time(r.get('observed_at') or r.get('requested_at'))+': '+str(r.get('status','chưa rõ kết quả')) for r in rows[-5:])
        return result(f'Ghi nhận {len(rows)} lệnh phù hợp, {facts["failed_count"]} lệnh báo thất bại. '+detail+'. Lệnh đã gửi hoặc timeout chưa chứng minh bơm/van đã chạy hay dừng.',facts,'answered' if rows else 'no_data')
    if tool=='alerts':
        if op=='active':rows=[r for r in rows if r.get('status') in ['open','active','unresolved']]
        if op=='last' and rows:rows=rows[-1:]
        if op=='severity' and rows:
            rank={'critical':4,'high':3,'warning':2,'medium':2,'low':1,'info':0}
            rows=sorted(rows,key=lambda r:rank.get(r.get('severity'),-1),reverse=True)[:1]
        facts={'alert_count':len(rows),'alerts':[{k:r.get(k) for k in ['code','text','status','severity','observed_at','zone_id']} for r in rows[-5:]]}
        if not rows:return result('Không có cảnh báo phù hợp được ghi nhận trong kỳ; không đồng nghĩa thiết bị chắc chắn bình thường khi dữ liệu có thể thiếu/trễ.',facts,'no_data')
        return result(f'Có {len(rows)} cảnh báo phù hợp. '+'; '.join(str(r.get('text') or r.get('message') or r.get('code') or 'chưa có nội dung')+' lúc '+display_time(r.get('observed_at'))+'; mức '+str(r.get('severity','chưa rõ')) for r in rows[-5:])+'. Đây là cảnh báo đã ghi nhận, chưa tự xác nhận nguyên nhân ngoài hiện trường.',facts)
    if tool in ['connection','operation']:
        from .answers import render_tool,connectivity
        if tool=='operation' and plan.get('historical'):
            facts={'status_record_count':len(rows),'pump_running_records':sum(flag(r.get('pump_running')) is True for r in rows),'unknown_pump_records':sum(flag(r.get('pump_running')) is None for r in rows)}
            return result(f'Trong kỳ có {len(rows)} bản ghi trạng thái: {facts["pump_running_records"]} bản ghi bơm chạy, {facts["unknown_pump_records"]} bản ghi chưa rõ. Đây là số bản ghi, không phải số lần bật hay tổng thời gian chạy; không suy ra hoạt động trong khoảng thiếu dữ liệu.',facts,'answered' if rows else 'no_data')
        value=render_tool(tool,{**data,'items':rows},plan,message,profile,observer,now=now)
        if tool=='connection' and has(text,'tu luc nao','lan cuoi','bao lau'):
            value+=' Mốc gửi dữ liệu cuối không xác định chính xác thời điểm mất kết nối bắt đầu.'
        connection=connectivity(rows[-1] if rows else {},observer,now)
        return result(value,{'last_observed_at':rows[-1].get('observed_at') if rows else None,'connection_code':connection['code']},'partial' if connection['code']=='UNKNOWN' else 'answered')
    return result('Câu hỏi chưa được hỗ trợ trong phạm vi dữ liệu thiết bị.',status='out_of_scope')
