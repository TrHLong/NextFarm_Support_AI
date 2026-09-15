"""Declared synthetic HTTP fixtures; regression acceptance, NOT field accuracy."""
import csv,json,copy
from pathlib import Path
from datetime import datetime,timezone,timedelta
from functools import partial
import pytest,httpx
from fastapi.testclient import TestClient
from nextfarm_device import api,store
from nextfarm_device.verified_answers import answer

NOW=datetime(2026,9,14,5,tzinfo=timezone.utc)
DAY=NOW.astimezone(timezone(timedelta(hours=7))).replace(hour=0,minute=0,second=0,microsecond=0)
def iso(value):return value.isoformat()
def at(hour,days=0):return iso(DAY+timedelta(hours=hour,days=days))
def fixture_data():
    def sensor(i,zone,when,moisture,temp,ec,ph):return {'event_id':i,'zone_id':zone,'observed_at':when,'soil_moisture':moisture,'temperature':temp,'ec':ec,'ph':ph,'air_humidity':70,'flow_rate':8,'quality':'good'}
    def run(i,zone,hour,minutes,water,fert,result,days=0,channel=0):return {'run_id':i,'zone_id':zone,'started_at':at(hour,days),'ended_at':iso(DAY+timedelta(days=days,hours=hour,minutes=minutes)),'observed_at':iso(DAY+timedelta(days=days,hours=hour,minutes=minutes)),
      'water_liters':water,'fertilizer_ml':fert,'result':result,'volume_valid':True,'counter_reset':False,'fertilizer_channel':channel}
    return {
      'sensor_readings':[sensor('S1','zone_a',at(8),40,26,1.2,6),sensor('S2','zone_a',at(10),60,30,1.6,6.4),
        sensor('S3','zone_a',iso(NOW-timedelta(seconds=60)),62,31,1.8,6.5),sensor('S4','zone_b',iso(NOW-timedelta(seconds=30)),50,28,1.4,6),sensor('SY','zone_a',at(10,-1),35,25,1,6)],
      'irrigation_runs':[run('R1','zone_a',6,10,100,10,'success'),run('R2','zone_a',8,20,200,20,'success'),run('R3','zone_a',10,30,None,None,'failed'),run('R4','zone_b',9,15,50,5,'success',channel=1),run('RY','zone_a',7,5,80,8,'success',days=-1)],
      'device_status':[{'observed_at':iso(NOW-timedelta(seconds=5)),'pump_running':True,'valve_running':True,'fertilizer_running':False,'fertilizer_requested':True,'dosage_configured':True,'meter_configured':True,'fertilizer_stop_latched':True,'outputs':[{'port':1,'role':'water_pump','running':True},{'port':2,'role':'zone_valve','running':True,'zone_id':'zone_a'},{'port':3,'role':'fertilizer_pump','running':False}]}],
      'connection_observer':[{'observed_at':iso(NOW-timedelta(seconds=5)),'power_confirmed':True,'mqtt_connected':True,'source':'declared_test_observer'}],
      'irrigation_schedules':[{'observed_at':at(0),'name':'Lịch A','zone_id':'zone_a','start_time':'06:00','duration_minutes':10,'enabled':True},{'observed_at':at(0),'name':'Lịch B','zone_id':'zone_b','every_hours':6,'duration_minutes':15,'enabled':False}],
      'control_commands':[{'observed_at':at(8),'requested_by':'farmer_long','command':'start_pump','status':'accepted'},{'observed_at':at(9),'requested_by':'farmer_long','command':'open_valve','status':'failed'},{'observed_at':at(10),'requested_by':'farmer_long','command':'stop_pump','status':'pending'}],
      'alerts':[{'observed_at':at(11),'zone_id':'zone_a','code':'A1','text':'Khóa bơm phân đang chốt','severity':'critical','status':'open'},
        {'observed_at':at(10),'zone_id':'zone_a','code':'A2','text':'Số đo từng vượt ngưỡng','severity':'warning','status':'resolved'},
        {'observed_at':at(9),'zone_id':'zone_b','code':'A3','text':'Thiếu số đo ở khu B','severity':'high','status':'open'}],
      'device_profile':[]}

@pytest.fixture
def farmer_chat(monkeypatch):
    dataset=fixture_data();requests=[];audit=[];responses=[];options={}
    profile={'zones':[{'zone_id':'zone_a','valve_port':2,'area_m2':100},{'zone_id':'zone_b','valve_port':4,'area_m2':200}],
      'crop':'Cà chua','area_m2':300,'model':'ESP32-S3','installed_sensors':['soil_moisture','temperature','ec','ph'],
      'thresholds':{'soil_moisture':[55,75],'ec':[1,2.5],'ph':[5.5,7]},'agronomy_approved':False,'outputs':[]}
    cabinet={'device_id':'cabinet_long','customer_id':'customer_long','device_name':'Tủ vườn Long','data_origin':'synthetic_test_fixture_only','profile':profile}
    monkeypatch.setattr(store,'user_context',lambda token:{'user_id':'farmer_long','role':'farmer'})
    monkeypatch.setattr(store,'authorize_device',lambda *args:cabinet)
    monkeypatch.setattr(api,'verified_answer',partial(answer,now=NOW))
    class DB:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def execute(self,sql,params):
            assert sql.startswith('INSERT INTO device_db.chat_log');audit.append(params);return self
        def fetchone(self):return {'id':len(audit)}
    monkeypatch.setattr(store,'connect',DB)
    client=TestClient(api.chat_app());original=httpx.Client
    def reply(request):
        requests.append(request);assert request.headers['Authorization']=='Bearer fixture'
        if request.url.path.endswith('/predict'):return httpx.Response(200,json={'device_id':'cabinet_long','predictions':[],'status':'NOT_VALIDATED'})
        if options.get('http_error'):return httpx.Response(options['http_error'],json={'detail':'fixture error'})
        assert request.url.path=='/devices/cabinet_long/data'
        group=request.url.params['group'];period=request.url.params['period'];zone=request.url.params.get('zone_id')
        rows=copy.deepcopy(dataset[group]);rows=[r for r in rows if not zone or r.get('zone_id')==zone]
        if group in ['device_status','connection_observer']:rows=rows[-1:]
        elif group=='irrigation_schedules':pass
        elif period=='latest':rows=sorted(rows,key=lambda r:datetime.fromisoformat(r['observed_at']))[-1:]
        elif period=='latest_all':
            latest={}
            for row in sorted(rows,key=lambda r:datetime.fromisoformat(r['observed_at'])):latest[row.get('zone_id')]=row
            rows=list(latest.values())
        else:
            start,end=store.period_bounds(period,NOW)
            rows=[r for r in rows if start<=datetime.fromisoformat(r['observed_at'])<end]
        value={'device_id':'cabinet_long','customer_id':options.get('customer_id','customer_long'),'items':rows,'truncated':options.get('truncated',False),'period':period,'zone_id':zone}
        responses.append(value);return httpx.Response(200,json=value)
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(reply),**kw))
    def ask(message):
        response=client.post('/chat',json={'device_id':'cabinet_long','message':message},headers={'Authorization':'Bearer fixture'})
        return response
    return ask,dataset,requests,options,audit,responses

def facts(response,tool):
    assert response.status_code==200,response.text
    body=response.json();return next(r['facts'] for r in body['trace']['results'] if r['request']['tool']==tool)

BANK=list(csv.DictReader((Path(__file__).parents[1]/'benchmarks/farmer-v13/questions.csv').open(encoding='utf-8-sig')))
@pytest.mark.parametrize('case',BANK,ids=lambda x:x['id'])
def test_authored_farmer_question_routes_and_executes(case,farmer_chat):
    ask,data,requests,options,audit,responses=farmer_chat
    response=ask(case['question']);assert response.status_code==200,response.text
    body=response.json();assert case['expected_tool'] in body['intent']
    assert body['answer'] and body['trace']['scope_verified'] and body['trace']['training_use_allowed'] is False
    if case['expected_tool'] in ['out_of_scope','clarify','read_only_policy']:assert requests==[]
    if case['expected_tool']=='out_of_scope':assert 'ngoài phạm vi dữ liệu thiết bị' in body['answer']
    assert audit and all(x['customer_id']=='customer_long' for x in responses)

@pytest.mark.parametrize('question,path,expected',[
 ('Độ ẩm khu A hiện tại?',('sensor','soil_moisture','value'),62),
 ('Độ ẩm khu B hiện tại?',('sensor','soil_moisture','value'),50),
 ('Nhiệt độ trung bình khu A hôm nay?',('sensor_history','temperature','mean'),29),
 ('Độ ẩm cao nhất khu A hôm nay?',('sensor_history','soil_moisture','max'),62),
 ('Độ ẩm thấp nhất khu A hôm nay?',('sensor_history','soil_moisture','min'),40),
 ('Hôm nay tưới mấy lần?',('irrigation','run_count'),4),
 ('Hôm nay dùng bao nhiêu nước?',('irrigation','water_liters'),350),
 ('Khu A hôm nay dùng bao nhiêu nước?',('irrigation','water_liters'),300),
 ('Hôm qua dùng bao nhiêu nước?',('irrigation','water_liters'),80),
 ('Hôm nay tưới bao lâu?',('irrigation','duration_minutes'),75),
 ('Hôm nay tổng phân đã châm?',('irrigation','fertilizer_ml'),35),
 ('Hôm nay tưới nhiều nước hơn hôm qua không?',('irrigation','water_difference_liters'),270),
 ('Lần tưới nào dùng nhiều nước nhất hôm nay?',('irrigation','selected_run','run_id'),'R2'),
 ('Lần tưới cuối lúc nào?',('irrigation','selected_run','run_id'),'R3'),
 ('Ca tưới nào thất bại hôm nay?',('irrigation','failed_count'),1),
 ('Bao nhiêu ca tưới thành công hôm nay?',('irrigation','run_count'),3),
 ('Hôm nay có mấy cảnh báo?',('alerts','alert_count'),3),
 ('Cảnh báo nào chưa xử lý?',('alerts','alert_count'),2),
 ('Hôm nay có bao nhiêu lệnh bị lỗi?',('commands','failed_count'),1),
 ('Lệnh nào đang chờ xác nhận?',('commands','command_count'),1),
 ('Lịch nào đang bật?',('schedules','schedule_count'),1),
 ('Lịch nào đang tắt?',('schedules','schedule_count'),1),
 ('Diện tích khu A là bao nhiêu?',('profile','area_m2'),100),
 ('Vườn tôi đang trồng cây gì?',('profile','crop'),'Cà chua'),
 ('Khu A nối với van số mấy?',('profile','valve_port'),2),
])
def test_exact_grounded_business_facts(question,path,expected,farmer_chat):
    response=farmer_chat[0](question);value=facts(response,path[0])
    for key in path[1:]:value=value[key]
    assert value==expected

def test_each_clause_owns_its_metric_zone_and_period(farmer_chat):
    body=farmer_chat[0]('Độ ẩm khu A hôm nay và nhiệt độ khu B hôm qua?').json()
    tasks=body['trace']['plan']['requests']
    assert [(p['metric'],p['zone_id'],p['period']) for p in tasks]==[('soil_moisture','zone_a','today'),('temperature','zone_b','yesterday')]
    assert 'Chưa có số đo đúng khu/kỳ' in body['answer']

def test_multiple_metrics_reuse_one_scoped_api_read(farmer_chat):
    response=farmer_chat[0]('Cho xem cả EC và pH khu A')
    assert response.status_code==200 and len(farmer_chat[2])==1
    values=response.json()['trace']['results'];assert values[0]['facts']['ec']['value']==1.8 and values[1]['facts']['ph']['value']==6.5

def test_invalid_latest_measurement_is_not_replaced_by_old_good_value(farmer_chat):
    farmer_chat[1]['sensor_readings'][2]['soil_moisture']=999
    response=farmer_chat[0]('Độ ẩm khu A hiện tại?');assert facts(response,'sensor')['soil_moisture']['value'] is None
    assert '999' not in response.json()['answer'] and '60.000' not in response.json()['answer']

def test_reset_negative_nan_and_missing_water_do_not_inflate_total(farmer_chat):
    runs=farmer_chat[1]['irrigation_runs'];runs[0]['counter_reset']=True;runs[1]['water_liters']=-500;runs[3]['water_liters']='NaN'
    response=farmer_chat[0]('Hôm nay dùng bao nhiêu nước?');f=facts(response,'irrigation')
    assert f['water_liters'] is None and f['water_missing_count']==4
    assert 'không xem thiếu là 0' in response.json()['answer']

@pytest.mark.parametrize('option,value,expected_status',[('customer_id','customer_minh',502),('http_error',503,200),('truncated',True,200)])
def test_wrong_owner_or_incomplete_backend_never_yields_normal_total(option,value,expected_status,farmer_chat):
    farmer_chat[3][option]=value;response=farmer_chat[0]('Hôm nay dùng bao nhiêu nước?');assert response.status_code==expected_status
    if expected_status==200:assert response.json()['trace']['results'][0]['status'] in ['partial','data_unavailable']

def test_future_horizon_does_not_fall_back_to_current_reading(farmer_chat):
    response=farmer_chat[0]('Độ ẩm ngày mai bao nhiêu?');body=response.json()
    assert body['trace']['results'][0]['status']=='forecast_unavailable'
    assert all(r.url.path.endswith('/predict') for r in farmer_chat[2])

def test_two_outage_causes_use_independent_observer(farmer_chat):
    obs=farmer_chat[1]['connection_observer'][0];obs.update(power_confirmed=False,mqtt_connected=False)
    assert 'xác nhận tủ mất nguồn' in farmer_chat[0]('Tủ có bị mất điện không?').json()['answer']
    obs['power_confirmed']=True
    assert 'Nguồn tủ vẫn được xác nhận' in farmer_chat[0]('Tủ có bị mất điện không?').json()['answer']

def test_multi_zone_latest_is_not_one_arbitrary_zone(farmer_chat):
    f=facts(farmer_chat[0]('Độ ẩm hiện tại bao nhiêu?'),'sensor')
    assert f['zones']['zone_a']['soil_moisture']['value']==62 and f['zones']['zone_b']['soil_moisture']['value']==50

def test_stale_sensor_is_labeled_stale(farmer_chat):
    rows=farmer_chat[1]['sensor_readings'];rows[2]['observed_at']=at(10,0)
    response=farmer_chat[0]('Độ ẩm khu A hiện tại?')
    assert facts(response,'sensor')['soil_moisture']['stale'] is True

@pytest.mark.parametrize('question,tool',[('Ca tưới gần nhất hôm qua là lúc nào?','irrigation'),('Cảnh báo mới nhất hôm qua?','alerts'),('Lệnh gần nhất hôm qua?','commands')])
def test_latest_with_explicit_period_never_reads_all_history(question,tool,farmer_chat):
    response=farmer_chat[0](question)
    assert response.status_code==200
    assert farmer_chat[2][0].url.params['period']=='yesterday'
    f=facts(response,tool)
    if tool=='irrigation':assert f['selected_run']['run_id']=='RY' and f['water_liters']==80
    else:assert f[{'alerts':'alert_count','commands':'command_count'}[tool]]==0

def test_unknown_fertilizer_channel_is_missing_not_zero(farmer_chat):
    response=farmer_chat[0]('Hôm nay bồn phân số 8 dùng bao nhiêu?')
    assert facts(response,'irrigation')['water_liters'] is None
    assert response.json()['trace']['results'][0]['status']=='no_data'

@pytest.mark.parametrize('stamp',['invalid','2026-09-14T11:00:00'])
def test_invalid_or_timezone_less_status_never_proves_online(stamp):
    from nextfarm_device.answers import connectivity
    assert connectivity({'observed_at':stamp},now=NOW)['code']=='UNKNOWN'

def test_explicit_offline_is_not_connected():
    from nextfarm_device.answers import connectivity
    assert connectivity({'observed_at':iso(NOW),'online':False},now=NOW)['code']=='UNKNOWN'

def test_unclosed_or_future_runs_are_not_completed_water_totals():
    rows=fixture_data()['irrigation_runs'][:2]
    rows[0]['ended_at']=None;rows[1]['ended_at']=iso(NOW+timedelta(hours=1))
    value=answer('irrigation',{'items':rows},{'period':'today'},'Tưới hôm nay',{},now=NOW)
    assert value['facts']['run_count']==0 and value['facts']['water_liters'] is None

def test_comparison_filters_invalid_previous_timestamp():
    rows=fixture_data()['sensor_readings']
    previous={**rows[0],'observed_at':'invalid','temperature':99}
    value=answer('sensor_history',{'items':[rows[2]],'previous_items':[previous]},
      {'metric':'temperature','metrics':['temperature'],'operation':'compare'},'So sánh nhiệt độ',{},now=NOW)
    assert value['facts']['temperature']['previous_mean'] is None
