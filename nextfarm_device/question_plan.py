"""Device-only, explicit query planning. Unknown requests never default to a value."""
import re,unicodedata

def norm(text):
    text=''.join(c for c in unicodedata.normalize('NFD',text.lower().replace('đ','d')) if unicodedata.category(c)!='Mn')
    return re.sub(r'\s+',' ',text).strip()

def has(text,*terms):return any(re.search(r'\b'+re.escape(term)+r'\b',text) for term in terms)

def period_of(text):
    if has(text,'so sanh','nhieu hon','it hon','nhieu nuoc hon'):
        if has(text,'hom nay') and has(text,'hom qua'):return 'today'
        if has(text,'tuan nay') and has(text,'tuan truoc'):return 'week'
        if has(text,'thang nay') and has(text,'thang truoc'):return 'month'
    dates=re.findall(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b',text)
    if dates:
        from datetime import date
        try:parsed=[date(int(y),int(m),int(d)).isoformat() for d,m,y in dates]
        except ValueError:return 'invalid'
        if len(parsed)==1:return 'date:'+parsed[0]
        if len(parsed)==2 and parsed[0]<=parsed[1]:return 'range:'+':'.join(parsed)
        return 'invalid'
    days=re.search(r'\b(\d+) ngay (?:qua|gan day)\b',text)
    if days:return 'days:'+days.group(1) if 1<=int(days.group(1))<=90 else 'invalid'
    hours=re.search(r'\b(\d+) (?:gio|tieng) (?:qua|gan day)\b',text)
    if hours:
        value=int(hours.group(1))
        if not 1<=value<=2160:return 'invalid'
        return 'days:'+str(value//24) if value%24==0 else 'hours:'+str(value)
    for phrase,value in [('sang nay','morning'),('trua nay','noon'),('chieu nay','afternoon'),('toi nay','evening'),('hom qua','yesterday'),('thang truoc','last_month'),('thang nay','month'),('tuan truoc','last_week'),('tuan nay','week'),('hom nay','today')]:
        if has(text,phrase):return value
    if has(text,'hom truoc','gan day','nam ngoai','nam nay','nam truoc'):return 'ambiguous'
    return None

def metrics_of(text):
    values=[]
    if has(text,'do am khong khi','am khong khi','khong khi am','khong khi kho'):values.append('air_humidity');text=text.replace('do am khong khi','').replace('am khong khi','')
    if has(text,'do am','am dat','dat am','dat kho','vung re kho','can tuoi chua') or (has(text,'dat') and has(text,'am')):values.append('soil_moisture')
    for terms,key in [(('nhiet do','bao nhieu do','nong nhat','nong khong','nong qua'),'temperature'),(('ec',),'ec'),(('ph',),'ph'),(('anh sang','buc xa','par'),'light'),(('luu luong','nuoc chay manh','nuoc chay yeu'),'flow_rate'),(('dien ap',),'supply_voltage'),(('ap suat',),'pressure'),(('cuong do song','rssi'),'rssi')]:
        if has(text,*terms):values.append(key)
    return values

OUTSIDE=['gia vang','gia may bom','gia nong san','ban gia','mua cam bien','mua may','vay tien','co phieu','bitcoin','thoi tiet','troi co mua','du bao mua','phun thuoc','la bi vang','la cay bi vang','benh cay','loai phan nao','bon phan gi','bai van','ke chuyen','nau canh','nau an','cong thuc nau','viet code','code hack','bo moi gioi han','bo qua quy tac']
GARDEN_RELATED=['vuon','khu','cay','ca chua','dat','nuoc','tuoi','phan','cam bien','bom','van','thiet bi','sau benh','mua']
IDENTITY=['chatgpt','gemini','llm','mo hinh nao','dung mo hinh gi','dung ai nao']
MODEL_MAP={'soil_moisture':'moisture_forecast','temperature':'temperature_forecast','air_humidity':'air_humidity_forecast',
  'ec':'ec_forecast','ph':'ph_forecast','light':'light_forecast'}
FAULTS=[(('mat nguon','mat dien'),'power_loss_forecast'),(('mqtt','mat ket noi'),'mqtt_loss_forecast'),(('ro ri',),'leak_forecast'),(('mat luu luong',),'flow_fault_forecast'),(('loi cam bien',),'sensor_fault_forecast'),(('tuoi that bai','ca tuoi gian doan'),'irrigation_failure_forecast')]

def forecast_horizons(text,metrics):
    """Return user-requested future horizons; six hours is the agronomic MVP default."""
    values=[]
    for amount,unit in re.findall(r'\b(\d+)\s*(phut|gio|tieng|h)\b',text):
        minutes=int(amount)*(1 if unit=='phut' else 60)
        if 1<=minutes<=72*60:values.append(minutes)
    ranged=re.search(r'\b(\d+)\s*[-–]\s*(\d+)\s*phut\b',text)
    if ranged:values.extend(int(value) for value in ranged.groups())
    if has(text,'nua tieng'):values.append(30)
    if has(text,'ngay mai') and 1440 not in values:values.append(1440)
    if values:return sorted(dict.fromkeys(values))
    # Fault probabilities remain an immediate-control question. Sensor
    # forecasts default to the same-day horizon requested by agronomy users.
    return [360] if metrics else [60]

def operation_of(text):
    if has(text,'danh sach','liet ke','nhung lan','cac lan','thoi gian cua','nhat ky tuoi'):return 'list'
    if has(text,'may van','bao nhieu van','dem van'):return 'count_open'
    if has(text,'bom nuoc') and has(text,'bom phan') and has(text,'hom nay','hom qua','tuan nay','thang nay'):return 'ran_in_period'
    if has(text,'so sanh','nhieu hon','it hon','nhieu nuoc hon'):return 'compare'
    if has(text,'khu nao'):return 'compare_zones'
    if has(text,'cao nhat','nhieu nhat','nhieu nuoc nhat','lon nhat','nong nhat'):return 'max'
    if has(text,'thap nhat','it nhat','kho nhat'):return 'min'
    if has(text,'tang hay giam','xu huong','bien dong'):return 'trend'
    if has(text,'trung binh'):return 'mean'
    if has(text,'lan cuoi','tuoi cuoi','gan nhat','moi nhat'):return 'last'
    if has(text,'thieu','reset'):return 'quality'
    if has(text,'thanh cong'):return 'success'
    if has(text,'that bai','bi loi','lenh loi'):return 'failed'
    if has(text,'dang cho','chua xac nhan'):return 'pending'
    if has(text,'chua xu ly','dang mo'):return 'active'
    if has(text,'nghiem trong'):return 'severity'
    if has(text,'dang tat'):return 'disabled'
    if has(text,'dang bat'):return 'enabled'
    if has(text,'trua nay'):return 'period_last'
    return 'summary'

def requested_fields_of(text):
    """Keep one business request when the farmer asks for several columns."""
    fields=[]
    for terms,key in [
        (('gio bat dau','bat dau','thoi diem bat dau'),'start_time'),
        (('gio ket thuc','ket thuc','hoan tat'),'end_time'),
        (('luong nuoc','bao nhieu nuoc','lit nuoc'),'water_liters'),
        (('luong phan','bao nhieu phan','ml phan','phan su dung'),'fertilizer_ml'),
        (('thoi luong','bao nhieu phut'),'duration_minutes'),
        (('trang thai','thanh cong','that bai'),'result'),
    ]:
        if has(text,*terms): fields.append(key)
    return fields

def _clause(text,inherited=None):
    inherited=inherited or {};metrics=metrics_of(text);period=period_of(text) or inherited.get('period','today')
    zones=re.findall(r'\bkhu\s+([a-z0-9]+)\b',text)
    zones=[x for x in zones if x not in ['nao','vuc','toi','cua']]
    zone='zone_'+zones[0] if zones else inherited.get('zone_id')
    port=re.search(r'\b(van|bom|cong|ngo ra)\s+(?:so\s+)?(\d+)\b',text)
    base={'period':period,'period_explicit':bool(period_of(text) or inherited.get('period_explicit')),'zone_id':zone,'metric':metrics[0] if metrics else None,'metrics':metrics,'operation':operation_of(text),
      'port':int(port.group(2)) if port else None,'requested_role':port.group(1) if port else None,'question':text,'model_names':[],
      'answer_mode':'current','requested_horizons':[],'requested_fields':requested_fields_of(text)}
    def tasks(tool,**kw):return [{**base,'tool':tool,**kw}]
    if has(text,*OUTSIDE):return tasks('out_of_scope',scope_kind='garden_data_missing' if has(text,*GARDEN_RELATED) else 'unrelated')
    if has(text,*IDENTITY):return tasks('identity')
    if has(text,'quyen truy cap','du lieu cua ai','nguon cau tra loi','csv','mui gio'):return tasks('provenance')
    command_history=has(text,'lenh','nhat ky dieu khien','ai vua','ai gui','ai tat','ai bat')
    diagnostic=has(text,'tai sao','vi sao','sao','chua','khong thay','ly do')
    actuation=bool(re.search(r'\b(bat|tat|mo|dung) (bom|van|tuoi)\b',text)) and not (command_history or diagnostic or has(text,'dang','co','khong','trang thai'))
    actuation=actuation or (has(text,'doi lich','sua lich','xoa','dat lich','tao lich','tang nguong','giam nguong') and not diagnostic)
    if actuation:return tasks('read_only_policy')
    if period in ['invalid','ambiguous']:return tasks('clarify',reason='Cần khoảng thời gian rõ ràng, ví dụ hôm qua hoặc ngày 10/09/2026.')
    forecast=has(text,'du bao','nguy co','ai danh gia','sap toi','phut nua','phut toi','gio toi','nua tieng','tieng nua') \
      or bool(re.search(r'\b(?:sau\s+\d+\s*(?:phut|gio|tieng|h)|(?:trong\s+)?\d+\s*(?:phut|gio|tieng|h)\s*(?:toi|nua))\b',text)) \
      or (metrics and has(text,'ngay mai','se bien dong','se tang','se giam'))
    if forecast:
        names=[MODEL_MAP[m] for m in metrics if m in MODEL_MAP]
        names.extend(name for terms,name in FAULTS if has(text,*terms))
        horizons=forecast_horizons(text,metrics)
        return tasks('models',model_names=list(dict.fromkeys(names)),horizon_minutes=horizons[0],requested_horizons=horizons,answer_mode='forecast')
    if command_history:return tasks('commands')
    is_profile=has(text,'ho so','thong tin tu','lap nhung cam bien','lap cam bien','cam bien nao','trong cay gi','dien tich','noi voi','van so may','loai gi','lay tu bon nao') or (has(text,'nguong') and has(text,'cai dat','cau hinh','bao nhieu') and not has(text,'vuot','co on','cao','thap'))
    if is_profile:return tasks('profile')
    fertilizer_diagnostic=diagnostic and has(text,'bon','bon phan','cham phan','phan','bom phan')
    if fertilizer_diagnostic:return tasks('operation',operation='reason')
    is_schedule=has(text,'lich tuoi','hen tuoi','lich cham phan','lich bon','cau hinh lich','lich nao') or (has(text,'ngay mai','mai') and has(text,'tuoi','bon phan'))
    if is_schedule:return tasks('schedules')
    if has(text,'ket noi','mqtt','mat dien','mat nguon','mat tin hieu','cam bien cam','khong gui','khong day','dung so','khong len du lieu','tu nay con','offline','online','dung yen','khong cap nhat','khong nhan duoc du lieu','mang bi dut','khong thay du lieu','tu gui trang thai'):return tasks('connection')
    if has(text,'canh bao','su co'):return tasks('alerts')
    overview=(has(text,'tom tat','tong quan','co gi bat thuong','viec can lam','can lam ngay','hoat dong on dinh','diem nao can chu y')
      or (zone and not metrics and has(text,'the nao','sao roi','on khong')))
    if overview:return tasks('overview',metrics=['soil_moisture','temperature','air_humidity','ec','ph'])
    if has(text,'thieu chi so','thieu truong','chat luong cam bien'):return tasks('sensor_quality')
    if has(text,'tuoi','nuoc','luong nuoc','tong phan','luong phan','phan su dung','phan da dung','dung bao nhieu phan','da dung bao nhieu phan','phan hom nay','cham het','phan da cham','bon phan so','dong ho','bo dem') and not has(text,'bom','van','lich') and not metrics:return tasks('irrigation')
    if has(text,'lich su tuoi'):return tasks('irrigation')
    if metrics:
        if has(text,'la gi','nghia la gi','do gi','don vi gi'):return tasks('knowledge')
        history=base['period_explicit'] or base['operation'] in ['max','min','mean','trend','compare','compare_zones'] or has(text,'lich su')
        device_metrics={'supply_voltage','pressure','rssi'}
        return [{**base,'tool':'device_metrics' if m in device_metrics else 'sensor_history' if history else 'sensor','metric':m,'metrics':[m],
          'answer_mode':'history' if history else 'current'} for m in metrics]
    if has(text,'so do','cam bien moi nhat','du lieu cam bien'):return tasks('sensor',metrics=['soil_moisture','temperature','air_humidity','ec','ph','flow_rate'])
    if has(text,'bom','van','cham phan','dang bon','chua bon','sao khong chay','sao toi bam','dung khan','ngo ra','cong so','trang thai cac ngo'):return tasks('operation',historical=base['period_explicit'])
    if has(text,'cau hinh','thiet bi'):return tasks('profile')
    if has(text,'vuon the nao','vuon hom nay'):return tasks('overview',metrics=['soil_moisture','temperature','air_humidity','ec','ph'])
    if len(text.split())<=4 or has(text,'cai do','no con','hom truoc','xem giup'):return tasks('clarify',reason='Bạn muốn hỏi số đo nào, khu nào hoặc lịch sử trong khoảng thời gian nào?')
    return tasks('out_of_scope',scope_kind='garden_data_missing' if has(text,*GARDEN_RELATED) else 'unrelated')

def route(message,_compound=True):
    text=norm(message)
    global_info={'period':period_of(text) or 'today','period_explicit':bool(period_of(text)),'zone_id':None}
    found=re.search(r'\bkhu\s+([a-z0-9]+)\b',text)
    if found and found.group(1) not in ['nao','vuc','toi','cua']:global_info['zone_id']='zone_'+found.group(1)
    # Overview questions may contain several phrasings but should yield one concise summary.
    overview_query=has(text,'tom tat','tong quan','co gi bat thuong','viec can lam','can lam ngay','hoat dong on dinh','diem nao can chu y')
    forecast_query=has(text,'du bao','sap toi','phut toi','gio toi','ngay mai','se bien dong','se tang','se giam') \
      or bool(re.search(r'\b(?:sau\s+\d+\s*(?:phut|gio|tieng|h)|(?:trong\s+)?\d+\s*(?:phut|gio|tieng|h)\s*(?:toi|nua))\b',text))
    command_query=has(text,'lenh','nhat ky dieu khien','ai vua','ai gui','ai tat','ai bat')
    combined_operation_query=has(text,'bom nuoc') and has(text,'bom phan')
    # A farmer's irrigation log with several requested columns is one query
    # plan. Splitting on "và" would otherwise lose fields such as fertilizer.
    irrigation_log_query=has(text,'nhat ky tuoi','lich su tuoi','ca tuoi') and bool(requested_fields_of(text))
    # Split independent requests; each request owns its metric/time/zone parameters.
    clauses=[text] if overview_query or forecast_query or command_query or combined_operation_query or irrigation_log_query else (re.split(r'\s+va\s+|\s+con\s+(?=khu\b)|[;?]',text) if _compound else [text])
    requests=[]
    for clause in clauses:
        if not clause.strip():continue
        inherited=dict(global_info)
        if requests and period_of(clause) and not metrics_of(clause) and len(clause.split())<=4:
            requests.append({**requests[-1],'period':period_of(clause),'period_explicit':True,'question':clause});continue
        tasks=_clause(clause.strip(),inherited)
        requests.extend(tasks)
    if not requests:requests=_clause(text,global_info)
    # Metric lists joined by "and" may leave a short second clause; inherit query operation.
    if len(requests)>1:
        for i in range(1,len(requests)):
            if requests[i]['tool']=='sensor' and requests[i-1]['tool']=='sensor_history' and requests[i]['operation']=='summary':
                requests[i]['tool']='sensor_history';requests[i]['operation']=requests[i-1]['operation']
    # A natural sentence such as "tưới mấy lần và hết bao nhiêu nước" is one
    # evidence query, not two identical answers. Keep genuinely different
    # metrics, zones, periods and operations while collapsing semantic copies.
    unique=[];seen=set()
    for task in requests:
        key=tuple(sorted((k,tuple(v) if isinstance(v,list) else v) for k,v in task.items() if k!='question'))
        if key in seen:continue
        seen.add(key);unique.append(task)
    requests=unique
    if len(requests)>12:requests=[{'tool':'clarify','period':'today','metric':None,'zone_id':None,'reason':'Câu hỏi có quá nhiều phần; hãy tách thành từng nhóm dữ liệu.','model_names':[]}]
    tools=list(dict.fromkeys(t['tool'] for t in requests));first=requests[0]
    return {**{k:v for k,v in first.items() if k!='tool'},'tools':tools,'requests':requests,
      'tool_periods':{t['tool']:t['period'] for t in requests},'model_names':list(dict.fromkeys(n for t in requests for n in t.get('model_names',[]))),
      'routing_method':'device_query_plan_v14','confidence':None,'scope':'device_data_only'}
