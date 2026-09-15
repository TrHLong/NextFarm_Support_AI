import os,json
from datetime import datetime,timezone,timedelta
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import HTTPException
import httpx
from .contracts import GROUPS

def connect():return psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row)

def user_context(token):
    if not token:raise HTTPException(401,'Thiếu phiên đăng nhập')
    try:
        r=httpx.post(os.getenv('IDENTITY_URL','http://identity-service:8000')+'/auth/verify',headers={'Authorization':token},timeout=10)
        if r.status_code!=200:raise HTTPException(401,'Phiên đăng nhập không hợp lệ')
        return r.json()['user']
    except httpx.HTTPError:raise HTTPException(503,'Dịch vụ xác thực chưa sẵn sàng')

def allowed_farms(user):return [f['farm_id'] for f in user.get('farms',[]) if f.get('can_read')]

def authorize_device(user,device_id):
    with connect() as db:
        row=db.execute('SELECT * FROM device_db.cabinets WHERE device_id=%s AND farm_id=ANY(%s)',(device_id,allowed_farms(user))).fetchone()
    if not row:raise HTTPException(403,'Tài khoản không có quyền đọc tủ này')
    return row

def period_bounds(period,now=None):
    now=now or datetime.now(timezone.utc);tz=timezone(timedelta(hours=7));local=now.astimezone(tz)
    day=local.replace(hour=0,minute=0,second=0,microsecond=0)
    week=day-timedelta(days=day.weekday());month=day.replace(day=1)
    if period=='today':return day,now
    if period=='yesterday':return day-timedelta(days=1),day
    if period=='week':return week,now
    if period=='last_week':return week-timedelta(days=7),week
    if period=='month':return month,now
    if period=='last_month':return (month-timedelta(days=1)).replace(day=1),month
    if period=='history':return now-timedelta(days=1),now
    if period in ['morning','afternoon','evening']:
        h0,h1={'morning':(0,12),'afternoon':(12,18),'evening':(18,24)}[period]
        start=day+timedelta(hours=h0);return start,max(start,min(now,day+timedelta(hours=h1)))
    if period.startswith(('date:','range:','days:')):
        try:
            bits=period.split(':')
            if bits[0]=='days':
                days=int(bits[1])
                if not 1<=days<=90:raise ValueError()
                return now-timedelta(days=days),now
            start=datetime.strptime(bits[1],'%Y-%m-%d').replace(tzinfo=tz)
            end=(datetime.strptime(bits[2],'%Y-%m-%d').replace(tzinfo=tz) if bits[0]=='range' else start)+timedelta(days=1)
            if end<=start or end-start>timedelta(days=90):raise ValueError()
            return start,max(start,min(end,now))
        except (IndexError,ValueError):raise HTTPException(422,'Khoảng ngày không hợp lệ hoặc dài hơn 90 ngày')
    raise HTTPException(422,'Khoảng thời gian không hỗ trợ')

def read_group(device_id,group,period='today',limit=20000,zone_id=None):
    if group not in GROUPS+['connection_observer','technical_logs']:raise HTTPException(422,'Nhóm dữ liệu không hợp lệ')
    if group=='device_profile':
        with connect() as db:return [db.execute('SELECT * FROM device_db.cabinets WHERE device_id=%s',(device_id,)).fetchone()]
    with connect() as db:
        selected_zone=zone_id if group in ['sensor_readings','irrigation_schedules','irrigation_runs','alerts','control_commands'] else None
        if period=='latest_all' and group=='sensor_readings':
            rows=db.execute("SELECT DISTINCT ON (payload->>'zone_id') id,payload,observed_at,received_at FROM device_db.events WHERE device_id=%s AND group_name=%s ORDER BY payload->>'zone_id',observed_at DESC",(device_id,group)).fetchall()
            rows=sorted(rows,key=lambda r:r['observed_at'],reverse=True)
        elif group in ['connection_observer','irrigation_schedules'] or (group=='device_status' and period in ['latest','today']) or period=='latest':
            rows=db.execute("SELECT id,payload,observed_at,received_at FROM device_db.events WHERE device_id=%s AND group_name=%s AND (%s::text IS NULL OR payload->>'zone_id'=%s) ORDER BY observed_at DESC LIMIT %s",(device_id,group,selected_zone,selected_zone,1 if group!='irrigation_schedules' else 100)).fetchall()
        else:
            start,end=period_bounds(period)
            rows=db.execute("SELECT id,payload,observed_at,received_at FROM device_db.events WHERE device_id=%s AND group_name=%s AND (%s::text IS NULL OR payload->>'zone_id'=%s) AND observed_at>=%s AND observed_at<%s ORDER BY observed_at DESC LIMIT %s",(device_id,group,selected_zone,selected_zone,start,end,limit)).fetchall()
            if len(rows)>=limit:raise HTTPException(422,'Quá nhiều bản ghi để xác nhận tổng đầy đủ; hãy thu hẹp khoảng thời gian')
    if group=='irrigation_schedules':
        seen=set();dedup=[]
        for r in rows:
            name=r['payload'].get('name')
            if name not in seen:dedup.append(r);seen.add(name)
        rows=dedup
    return [{**r['payload'],'event_id':r.get('id',r['payload'].get('event_id')),'device_id':device_id,'observed_at':r['observed_at'].isoformat(),'received_at':r['received_at'].isoformat()} for r in reversed(rows)]

def put_event(db,device_id,group,stamp,payload,event_id):
    result=db.execute('INSERT INTO device_db.events(device_id,group_name,observed_at,payload,event_key) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (device_id,event_key) DO NOTHING',
        (device_id,group,stamp,Jsonb(payload),event_id))
    return result.rowcount

def initialize_schema():
    with connect() as db:
        db.execute('SELECT pg_advisory_xact_lock(110009)')
        db.execute('''CREATE SCHEMA IF NOT EXISTS device_db;
        CREATE TABLE IF NOT EXISTS device_db.cabinets(
          device_id text PRIMARY KEY, customer_id text NOT NULL, farm_id text NOT NULL REFERENCES farm_db.farms(farm_id),
          device_name text NOT NULL, profile jsonb NOT NULL, data_origin text NOT NULL DEFAULT 'synthetic_device_spec_v11');
        CREATE TABLE IF NOT EXISTS device_db.events(
          id bigserial PRIMARY KEY, device_id text NOT NULL REFERENCES device_db.cabinets(device_id),
          group_name text NOT NULL, observed_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
          payload jsonb NOT NULL, event_key text NOT NULL, UNIQUE(device_id,event_key));
        CREATE INDEX IF NOT EXISTS device_event_lookup ON device_db.events(device_id,group_name,observed_at DESC);
        CREATE TABLE IF NOT EXISTS device_db.chat_log(
          id bigserial PRIMARY KEY,user_id text NOT NULL,device_id text NOT NULL REFERENCES device_db.cabinets(device_id),
          question text NOT NULL,answer text NOT NULL,trace jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
        CREATE TABLE IF NOT EXISTS device_db.read_audits(
          id bigserial PRIMARY KEY,user_id text NOT NULL,device_id text NOT NULL,group_name text NOT NULL,created_at timestamptz DEFAULT now());
        CREATE TABLE IF NOT EXISTS device_db.chat_feedback(
          id bigserial PRIMARY KEY,chat_id bigint NOT NULL REFERENCES device_db.chat_log(id),user_id text NOT NULL,
          useful boolean NOT NULL,comment text,training_use_allowed boolean NOT NULL DEFAULT false,created_at timestamptz DEFAULT now());''')
        for who,crop,profile_type in [('long','Cà chua','greenhouse'),('lan','Sầu riêng','open_field'),('minh','Rau ăn lá','net_house')]:
            profile={'model':'ESP32-S3 8DI/8DO','crop':crop,'profile_type':profile_type,'source':'company_spec_plus_declared_simulation_assumptions',
              'sensor_seconds':600,'status_seconds':5,'thresholds':{'soil_moisture':[55,75],'temperature':[18,32],'ec':[1,2.5],'ph':[5.5,7]},
              'agronomy_approved':False,'soil_type':None,'growth_stage':None,'area_m2':None,
              'zones':[{'zone_id':'zone_a','name':'Khu A','valve_port':2,'area_m2':None}],
              'installed_sensors':['soil_moisture','temperature','air_humidity','ec','ph','flow_rate'],
              'threshold_basis':'Demo configuration; requires agronomy approval before field use',
              'outputs':[{'port':1,'role':'Bơm nước'},{'port':2,'role':'Van vùng'},{'port':3,'role':'Bơm phân'},{'port':4,'role':'Van phân kênh 1'}],
              'fertilizer_channels':[{'channel':0,'display_name':'Kênh 1 / Bồn A','meter':2,'dosage_ml':288}],
              'schedules':[{'name':'Lịch demo tại bo','every_hours':6,'duration_minutes':30,'fertilizer_ml':288,'zone_id':'zone_a','valve_port':2}]}
            db.execute('INSERT INTO device_db.cabinets(device_id,customer_id,farm_id,device_name,profile) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(device_id) DO NOTHING',
                (f'cabinet_{who}',f'customer_{who}',f'farm_{who}',f'Tủ {crop} {who}',Jsonb(profile)))
            # Fill missing demo metadata without overwriting a customer's configured values.
            db.execute("UPDATE device_db.cabinets SET profile=%s::jsonb || profile WHERE device_id=%s AND profile->>'source'='company_spec_plus_declared_simulation_assumptions'",(Jsonb(profile),f'cabinet_{who}'))
            for field,legacy in [('fertilizer_channels',[{'channel':1,'name':'Bồn A','meter':2,'dosage_ml':288}]),('schedules',[{'name':'Lịch demo tại bo','every_hours':6,'duration_minutes':30,'fertilizer_ml':288}])]:
                db.execute("UPDATE device_db.cabinets SET profile=jsonb_set(profile,%s,%s::jsonb) WHERE device_id=%s AND profile->>'source'='company_spec_plus_declared_simulation_assumptions' AND profile->%s=%s::jsonb",([field],Jsonb(profile[field]),f'cabinet_{who}',field,Jsonb(legacy)))
