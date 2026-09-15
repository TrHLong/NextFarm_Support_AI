"""Exercise real chat routing/tool requests/rendering against declared HTTP fixtures."""
from datetime import datetime,timezone,timedelta
import httpx,pytest
from fastapi.testclient import TestClient
from nextfarm_device import api,store


@pytest.fixture
def chat_client(monkeypatch):
    now=datetime.now(timezone.utc);requests=[];saved=[]
    user={'user_id':'farmer_long','role':'farmer'}
    cabinet={'device_id':'cabinet_long','customer_id':'customer_long','device_name':'Tủ thử nghiệm',
             'data_origin':'synthetic_fixture','profile':{'zones':[{'zone_id':'zone_a'}]}}
    monkeypatch.setattr(store,'user_context',lambda token:user)
    monkeypatch.setattr(store,'authorize_device',lambda *args:cabinet)
    class DB:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,sql,params):saved.append(params);return self
        def fetchone(self):return {'id':1}
    monkeypatch.setattr(store,'connect',DB)
    client=TestClient(api.chat_app());original=httpx.Client
    def reply(request):
        requests.append(request)
        assert request.headers['authorization']=='Bearer fixture'
        assert request.url.path=='/devices/cabinet_long/data'
        group=request.url.params['group'];zone=request.url.params.get('zone_id')
        rows=[]
        if group=='sensor_readings':rows=[{'zone_id':'zone_a','soil_moisture':62,'quality':'good','observed_at':now.isoformat()}]
        elif group=='device_status':rows=[{'observed_at':now.isoformat(),'outputs':[{'port':3,'role':'fertilizer_pump','running':False}]}]
        elif group=='irrigation_runs':rows=[{'zone_id':'zone_a','observed_at':(now-timedelta(days=1)).isoformat(),'started_at':(now-timedelta(days=1,minutes=n)).isoformat(),'ended_at':(now-timedelta(days=1)).isoformat(),'water_liters':10,'fertilizer_ml':5} for n in [10,20]]
        if zone:rows=[row for row in rows if row.get('zone_id')==zone]
        return httpx.Response(200,json={'device_id':'cabinet_long','customer_id':'customer_long','zone_id':zone,'items':rows})
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(reply),**kw))
    return client,requests,saved


@pytest.mark.parametrize('question,expected,zone,period',[
 ('Độ ẩm đất khu A giờ bao nhiêu?','62.000','zone_a','latest'),
 ('Hôm qua tưới mấy lần, tổng bao nhiêu phút?','30.0 phút',None,'yesterday'),
 ('Van số 3 có đang chạy không?','không được cấu hình là van',None,'today'),
 ('Tuần này khu B có ngày nào không tưới không?','chưa cấu hình khu B','zone_b','week'),
])
def test_problem_b_question_reaches_scoped_api_and_keeps_evidence(chat_client,question,expected,zone,period):
    client,requests,saved=chat_client
    result=client.post('/chat',json={'device_id':'cabinet_long','message':question},headers={'Authorization':'Bearer fixture'})
    assert result.status_code==200;body=result.json()
    assert expected in body['answer'] and 'dữ liệu mô phỏng' in body['answer']
    assert body['trace']['training_use_allowed'] is False and body['trace']['scope_verified'] is True
    assert requests[0].url.params.get('zone_id')==zone and requests[0].url.params['period']==period
    assert saved and saved[0][0]=='farmer_long'


def test_zone_filter_precedes_latest_limit_in_store_query(monkeypatch):
    class DB:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,sql,params):
            assert sql.index("payload->>'zone_id'")<sql.index('ORDER BY')<sql.index('LIMIT')
            assert params==('cabinet_long','sensor_readings','zone_a','zone_a',1)
            return self
        def fetchall(self):return []
    monkeypatch.setattr(store,'connect',DB)
    assert store.read_group('cabinet_long','sensor_readings','latest',zone_id='zone_a')==[]
