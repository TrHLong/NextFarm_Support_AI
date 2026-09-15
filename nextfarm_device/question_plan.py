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
    for phrase,value in [('sang nay','morning'),('chieu nay','afternoon'),('toi nay','evening'),('hom qua','yesterday'),('thang truoc','last_month'),('thang nay','month'),('tuan truoc','last_week'),('tuan nay','week'),('hom nay','today')]:
        if has(text,phrase):return value
    if has(text,'hom truoc','gan day','nam ngoai','nam nay','nam truoc'):return 'ambiguous'
    return None

def metrics_of(text):
    values=[]
    if has(text,'do am khong khi','am khong khi'):values.append('air_humidity');text=text.replace('do am khong khi','').replace('am khong khi','')
    if has(text,'do am','am dat','dat kho') or (has(text,'dat') and has(text,'am')):values.append('soil_moisture')
    for terms,key in [(('nhiet do','bao nhieu do','nong nhat'),'temperature'),(('ec',),'ec'),(('ph',),'ph'),(('luu luong',),'flow_rate'),(('dien ap',),'supply_voltage'),(('ap suat',),'pressure'),(('cuong do song','rssi'),'rssi')]:
        if has(text,*terms):values.append(key)
    return values

OUTSIDE=['gia vang','gia may bom','gia nong san','ban gia','mua cam bien','mua may','vay tien','co phieu','bitcoin','thoi tiet','troi co mua','du bao mua','phun thuoc','la bi vang','la cay bi vang','benh cay','loai phan nao','bon phan gi','bai van','ke chuyen','nau canh','nau an','cong thuc nau','viet code','code hack','bo moi gioi han','bo qua quy tac']
IDENTITY=['chatgpt','gemini','llm','mo hinh nao','dung mo hinh gi','dung ai nao']
MODEL_MAP={'soil_moisture':'moisture_forecast','temperature':'temperature_forecast','ec':'ec_forecast','ph':'ph_forecast'}
FAULTS=[(('mat nguon','mat dien'),'power_loss_forecast'),(('mqtt','mat ket noi'),'mqtt_loss_forecast'),(('ro ri',),'leak_forecast'),(('mat luu luong',),'flow_fault_forecast'),(('loi cam bien',),'sensor_fault_forecast'),(('tuoi that bai','ca tuoi gian doan'),'irrigation_failure_forecast')]

def operation_of(text):
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
    return 'summary'

def _clause(text,inherited=None):
    inherited=inherited or {};metrics=metrics_of(text);period=period_of(text) or inherited.get('period','today')
    zones=re.findall(r'\bkhu\s+([a-z0-9]+)\b',text)
    zones=[x for x in zones if x not in ['nao','vuc','toi','cua']]
    zone='zone_'+zones[0] if zones else inherited.get('zone_id')
    port=re.search(r'\b(van|bom|cong|ngo ra)\s+(?:so\s+)?(\d+)\b',text)
    base={'period':period,'period_explicit':bool(period_of(text) or inherited.get('period_explicit')),'zone_id':zone,'metric':metrics[0] if metrics else None,'metrics':metrics,'operation':operation_of(text),
      'port':int(port.group(2)) if port else None,'requested_role':port.group(1) if port else None,'question':text,'model_names':[]}
    def tasks(tool,**kw):return [{**base,'tool':tool,**kw}]
    if has(text,*OUTSIDE):return tasks('out_of_scope')
    if has(text,*IDENTITY):return tasks('identity')
    if has(text,'quyen truy cap','du lieu cua ai','nguon cau tra loi','csv','mui gio'):return tasks('provenance')
    command_history=has(text,'lenh','nhat ky dieu khien','ai vua','ai gui','ai tat','ai bat')
    actuation=bool(re.search(r'\b(bat|tat|mo|dung) (bom|van|tuoi)\b',text)) and not (command_history or has(text,'tai sao','sao','dang','co','khong','chua','trang thai'))
    actuation=actuation or has(text,'doi lich','sua lich','xoa','dat lich','tao lich','tang nguong','giam nguong')
    if actuation:return tasks('read_only_policy')
    if period in ['invalid','ambiguous']:return tasks('clarify',reason='Cần khoảng thời gian rõ ràng, ví dụ hôm qua hoặc ngày 10/09/2026.')
    forecast=has(text,'du bao','nguy co','ai danh gia','phut nua','phut toi','gio toi','nua tieng','tieng nua','sau 30 phut','sau 1 gio') or (metrics and has(text,'ngay mai'))
    if forecast:
        names=[MODEL_MAP.get(m,'unsupported') for m in metrics]
        names.extend(name for terms,name in FAULTS if has(text,*terms))
        match=re.search(r'\b(\d+)\s*(phut|gio|tieng)\b',text)
        horizon=int(match.group(1))*(60 if match.group(2)!='phut' else 1) if match else 30 if has(text,'nua tieng') else 1440 if has(text,'ngay mai') else 60 if not metrics else 30
        return tasks('models',model_names=list(dict.fromkeys(names)),horizon_minutes=horizon)
    if command_history:return tasks('commands')
    is_profile=has(text,'ho so','thong tin tu','lap nhung cam bien','lap cam bien','cam bien nao','trong cay gi','dien tich','noi voi','van so may','loai gi','lay tu bon nao') or (has(text,'nguong') and has(text,'cai dat','cau hinh','bao nhieu') and not has(text,'vuot','co on','cao','thap'))
    if is_profile:return tasks('profile')
    is_schedule=has(text,'lich tuoi','hen tuoi','lich cham phan','lich bon','cau hinh lich','lich nao') or (has(text,'ngay mai','mai') and has(text,'tuoi','bon phan'))
    if is_schedule:return tasks('schedules')
    if has(text,'ket noi','mqtt','mat dien','mat nguon','mat tin hieu','cam bien cam','khong gui','khong day','dung so','khong len du lieu','tu nay con','offline','online','dung yen','khong cap nhat','khong nhan duoc du lieu','mang bi dut','khong thay du lieu','tu gui trang thai'):return tasks('connection')
    if has(text,'canh bao','su co','bat thuong'):return tasks('alerts')
    if has(text,'thieu chi so','thieu truong','chat luong cam bien'):return tasks('sensor_quality')
    if has(text,'tuoi','nuoc','luong nuoc','tong phan','cham het','phan da cham','bon phan so','dong ho','bo dem') and not has(text,'bom','van','lich') and not metrics:return tasks('irrigation')
    if has(text,'lich su tuoi'):return tasks('irrigation')
    if metrics:
        if has(text,'la gi','nghia la gi','do gi','don vi gi'):return tasks('knowledge')
        history=period!='today' or base['operation'] in ['max','min','mean','trend','compare','compare_zones'] or has(text,'lich su')
        return [{**base,'tool':'sensor_history' if history else 'sensor','metric':m,'metrics':[m]} for m in metrics]
    if has(text,'so do','cam bien moi nhat','du lieu cam bien'):return tasks('sensor',metrics=['soil_moisture','temperature','air_humidity','ec','ph','flow_rate'])
    if has(text,'bom','van','cham phan','dang bon','chua bon','sao khong chay','sao toi bam','dung khan','ngo ra','cong so','trang thai cac ngo'):return tasks('operation',historical=period!='today')
    if has(text,'cau hinh','thiet bi'):return tasks('profile')
    if has(text,'vuon the nao','vuon hom nay','tong quan'):return [{**base,'tool':t} for t in ['sensor','irrigation','connection','alerts']]
    if len(text.split())<=4 or has(text,'cai do','no con','hom truoc','xem giup'):return tasks('clarify',reason='Bạn muốn hỏi số đo nào, khu nào hoặc lịch sử trong khoảng thời gian nào?')
    return tasks('out_of_scope')

def route(message,_compound=True):
    text=norm(message)
    global_info={'period':period_of(text) or 'today','period_explicit':bool(period_of(text)),'zone_id':None}
    found=re.search(r'\bkhu\s+([a-z0-9]+)\b',text)
    if found and found.group(1) not in ['nao','vuc','toi','cua']:global_info['zone_id']='zone_'+found.group(1)
    # Split independent requests; each request owns its metric/time/zone parameters.
    clauses=re.split(r'\s+va\s+|\s+con\s+(?=khu\b)|[;?]',text) if _compound else [text]
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
    if len(requests)>12:requests=[{'tool':'clarify','period':'today','metric':None,'zone_id':None,'reason':'Câu hỏi có quá nhiều phần; hãy tách thành từng nhóm dữ liệu.','model_names':[]}]
    tools=list(dict.fromkeys(t['tool'] for t in requests));first=requests[0]
    return {**{k:v for k,v in first.items() if k!='tool'},'tools':tools,'requests':requests,
      'tool_periods':{t['tool']:t['period'] for t in requests},'model_names':list(dict.fromkeys(n for t in requests for n in t.get('model_names',[]))),
      'routing_method':'device_query_plan_v13','confidence':None,'scope':'device_data_only'}
