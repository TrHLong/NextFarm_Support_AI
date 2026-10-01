import os,json
from datetime import datetime,timezone,timedelta
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import HTTPException
import httpx
from .contracts import GROUPS
from .temporal import TZ, resolve_day_period

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
    now=now or datetime.now(timezone.utc);tz=TZ;local=now.astimezone(tz)
    day=local.replace(hour=0,minute=0,second=0,microsecond=0)
    week=day-timedelta(days=day.weekday());month=day.replace(day=1)
    if period=='today':return day,now
    if period=='yesterday':return day-timedelta(days=1),day
    if period=='week':return week,now
    if period=='last_week':return week-timedelta(days=7),week
    if period=='month':return month,now
    if period=='last_month':return (month-timedelta(days=1)).replace(day=1),month
    if period=='history':return now-timedelta(days=1),now
    if period in ['morning','noon','afternoon','evening']:
        return resolve_day_period(period, now)
    if period.startswith(('date:','range:','days:','hours:')):
        try:
            bits=period.split(':')
            if bits[0]=='hours':
                hours=int(bits[1])
                if not 1<=hours<=2160:raise ValueError()
                return now-timedelta(hours=hours),now
            if bits[0]=='days':
                days=int(bits[1])
                if not 1<=days<=90:raise ValueError()
                return now-timedelta(days=days),now
            start=datetime.strptime(bits[1],'%Y-%m-%d').replace(tzinfo=tz)
            end=(datetime.strptime(bits[2],'%Y-%m-%d').replace(tzinfo=tz) if bits[0]=='range' else start)+timedelta(days=1)
            if end<=start or end-start>timedelta(days=90):raise ValueError()
            return start,max(start,min(end,now))
        except (IndexError,ValueError):raise HTTPException(422,'Khoảng thời gian không hợp lệ hoặc dài hơn 90 ngày')
    raise HTTPException(422,'Khoảng thời gian không hỗ trợ')

def read_group(device_id,group,period='today',limit=20000,zone_id=None):
    if group not in GROUPS+['connection_observer','technical_logs']:raise HTTPException(422,'Nhóm dữ liệu không hợp lệ')
    if group=='device_profile':
        with connect() as db:return [db.execute('SELECT * FROM device_db.cabinets WHERE device_id=%s',(device_id,)).fetchone()]
    with connect() as db:
        # Alerts may belong to a zone or to the whole cabinet (power/network).
        # Read the cabinet-level set first, then keep the selected zone plus
        # cabinet-wide alerts instead of silently dropping the latter.
        alert_zone=zone_id if group=='alerts' else None
        # Older command records may not carry zone_id. Read the cabinet-level
        # audit and let the answer layer disclose whether zone scope is known.
        selected_zone=zone_id if group in ['sensor_readings','irrigation_schedules','irrigation_runs'] else None
        if period=='latest_all' and group=='sensor_readings':
            rows=db.execute("SELECT DISTINCT ON (payload->>'zone_id') id,payload,observed_at,received_at FROM device_db.events WHERE device_id=%s AND group_name=%s ORDER BY payload->>'zone_id',observed_at DESC",(device_id,group)).fetchall()
            rows=sorted(rows,key=lambda r:r['observed_at'],reverse=True)
        elif group in ['connection_observer','irrigation_schedules'] or (group=='device_status' and period=='latest') or period=='latest':
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
    if alert_zone:
        rows=[r for r in rows if r['payload'].get('zone_id') in [None,alert_zone]]
    return [{**r['payload'],'event_id':r.get('id',r['payload'].get('event_id')),'device_id':device_id,'observed_at':r['observed_at'].isoformat(),'received_at':r['received_at'].isoformat()} for r in reversed(rows)]

def put_event(db,device_id,group,stamp,payload,event_id):
    result=db.execute('INSERT INTO device_db.events(device_id,group_name,observed_at,payload,event_key) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (device_id,event_key) DO NOTHING',
        (device_id,group,stamp,Jsonb(payload),event_id))
    return result.rowcount

def demo_business_events(now=None):
    """A small, explicit demo baseline for farmer-facing business questions.

    The live simulator only completes an irrigation run at its next six-hour
    slot. A newly started demo would therefore look broken for hours. These
    date-scoped records make schedule/history/command examples available at
    startup without pretending they are field measurements.
    """
    now=now or datetime.now(timezone.utc);tz=timezone(timedelta(hours=7));local=now.astimezone(tz)
    day=local.replace(hour=0,minute=0,second=0,microsecond=0)
    if local>=day+timedelta(hours=6,minutes=25):
        start=day+timedelta(hours=6);end=start+timedelta(minutes=20)
    else:
        elapsed=max((local-day).total_seconds(),0)
        end=local-timedelta(seconds=min(120,elapsed/4))
        start=max(day,end-timedelta(minutes=min(20,elapsed/120)))
    duration=max((end-start).total_seconds()/60,0)
    stamp=end.astimezone(timezone.utc);date_key=day.strftime('%Y-%m-%d')
    source={'source':'synthetic_device_spec_v14','collection_version':'14.0.0','acquisition_method':'declared_demo_seed'}
    schedule={**source,'schedule_id':'demo_zone_a_morning','name':'Lịch tưới sáng Khu A','zone_id':'zone_a','valve_port':2,
      'start_time':'06:00','every_hours':6,'duration_minutes':20,'fertilizer_ml':288,'enabled':True}
    run={**source,'run_id':'demo_zone_a_'+date_key,'zone_id':'zone_a','valve_port':2,'fertilizer_channel':0,
      'started_at':start.astimezone(timezone.utc).isoformat(),'ended_at':stamp.isoformat(),'duration_minutes':duration,
      'water_liters':round(duration*12,2),'fertilizer_ml':round(min(duration,12)*24,2),'result':'completed',
      'volume_valid':True,'counter_reset':False,'volume_method':'declared_demo_baseline'}
    command={**source,'command_id':'demo_start_zone_a_'+date_key,'zone_id':'zone_a','requested_by':'Lịch tự động tại tủ',
      'command':'Bắt đầu tưới Khu A','status':'acknowledged','requested_at':start.astimezone(timezone.utc).isoformat()}
    return [
      ('irrigation_schedules',now,schedule,'demo-v14:schedule:zone_a:morning'),
      ('irrigation_runs',stamp,run,'demo-v14:run:'+date_key+':zone_a'),
      ('control_commands',start.astimezone(timezone.utc),command,'demo-v14:command:'+date_key+':zone_a')]

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
        demo_now=datetime.now(timezone.utc);demo_events=demo_business_events(demo_now);day_start,day_end=period_bounds('today',demo_now)
        for who,crop,profile_type in [('long','Cà chua','greenhouse'),('lan','Sầu riêng','open_field'),('minh','Rau ăn lá','net_house')]:
            profile={'model':'ESP32-S3 8DI/8DO','crop':crop,'profile_type':profile_type,'source':'company_spec_plus_declared_simulation_assumptions',
              'sensor_seconds':600,'status_seconds':5,'thresholds':{'soil_moisture':[55,75],'temperature':[18,32],'ec':[1,2.5],'ph':[5.5,7]},
              'agronomy_approved':False,'soil_type':None,'growth_stage':None,'area_m2':None,
              'zones':[{'zone_id':'zone_a','name':'Khu A','valve_port':2,'area_m2':None}],
              'installed_sensors':['soil_moisture','temperature','air_humidity','ec','ph','flow_rate'],
              'threshold_basis':'Demo configuration; requires agronomy approval before field use',
              'outputs':[{'port':1,'role':'Bơm nước'},{'port':2,'role':'Van vùng'},{'port':3,'role':'Bơm phân'},{'port':4,'role':'Van phân kênh 1'}],
              'fertilizer_channels':[{'channel':0,'display_name':'Kênh 1 / Bồn A','meter':2,'dosage_ml':288}],
              'schedules':[{'schedule_id':'demo_zone_a_morning','name':'Lịch tưới sáng Khu A','start_time':'06:00','every_hours':6,'duration_minutes':20,'fertilizer_ml':288,'enabled':True,'zone_id':'zone_a','valve_port':2}]}
            db.execute('INSERT INTO device_db.cabinets(device_id,customer_id,farm_id,device_name,profile) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(device_id) DO NOTHING',
                (f'cabinet_{who}',f'customer_{who}',f'farm_{who}',f'Tủ {crop} {who}',Jsonb(profile)))
            # Fill missing demo metadata without overwriting a customer's configured values.
            db.execute("UPDATE device_db.cabinets SET profile=%s::jsonb || profile WHERE device_id=%s AND profile->>'source'='company_spec_plus_declared_simulation_assumptions'",(Jsonb(profile),f'cabinet_{who}'))
            for field,legacy in [('fertilizer_channels',[{'channel':1,'name':'Bồn A','meter':2,'dosage_ml':288}]),('schedules',[{'name':'Lịch demo tại bo','every_hours':6,'duration_minutes':30,'fertilizer_ml':288}])]:
                db.execute("UPDATE device_db.cabinets SET profile=jsonb_set(profile,%s,%s::jsonb) WHERE device_id=%s AND profile->>'source'='company_spec_plus_declared_simulation_assumptions' AND profile->%s=%s::jsonb",([field],Jsonb(profile[field]),f'cabinet_{who}',field,Jsonb(legacy)))
            # Demo cabinets are synthetic by declaration, so keeping their
            # example schedule aligned with the farmer UI cannot overwrite
            # production configuration.
            db.execute("UPDATE device_db.cabinets SET profile=jsonb_set(profile,'{schedules}',%s::jsonb) WHERE device_id=%s AND data_origin LIKE 'synthetic%%'",(Jsonb(profile['schedules']),f'cabinet_{who}'))
            # Normalize the older synthetic schedule snapshot so it does not
            # appear as a second schedule after this demo-contract upgrade.
            db.execute("UPDATE device_db.events SET payload=payload || %s::jsonb WHERE device_id=%s AND group_name='irrigation_schedules' AND payload->>'name'='Lịch demo tại bo' AND payload->>'source' LIKE 'synthetic%%'",(Jsonb(profile['schedules'][0]),f'cabinet_{who}'))
            for group,stamp,payload,event_key in demo_events:
                if group in ['irrigation_runs','control_commands']:
                    exists=db.execute('SELECT 1 FROM device_db.events WHERE device_id=%s AND group_name=%s AND observed_at>=%s AND observed_at<%s LIMIT 1',(f'cabinet_{who}',group,day_start,day_end)).fetchone()
                    if exists:continue
                put_event(db,f'cabinet_{who}',group,stamp,payload,event_key)
