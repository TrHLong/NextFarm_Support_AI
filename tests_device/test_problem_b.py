"""Acceptance of code using declared fixtures; not field/model accuracy evidence."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import json,math
import pytest
import pandas as pd
from fastapi import HTTPException
from fastapi.testclient import TestClient
from nextfarm_device import store,api
from nextfarm_device.answers import route,render_tool,fertilizer_reasons,connectivity
from nextfarm_device.collection import VERSION,acquisition_gate,clean_group,export_window
from nextfarm_device.runtime_training import train_snapshot,seal_frame


BASE=datetime(2026,1,1,tzinfo=timezone.utc)


def test_constant_target_does_not_fake_baseline_improvement():
    from nextfarm_device.runtime_training import regression_gain
    assert regression_gain(0,0)==0
    assert regression_gain(1,0)<0
    assert regression_gain(.8,1)==pytest.approx(.2)


def test_future_question_cannot_be_answered_as_current_measurement():
    assert route('Độ ẩm ngày mai bao nhiêu?')['tools']==['models']
    assert route('Dự án dùng mô hình nào?')['tools']==['identity']


def test_invalid_sensor_cannot_be_presented_as_trustworthy_value():
    from nextfarm_device.answers import sensor_answer
    answer=sensor_answer({'items':[{'soil_moisture':999,'observed_at':datetime.now(timezone.utc).isoformat()}]},'soil_moisture','độ ẩm',{})
    assert 'không hợp lệ' in answer and '999' not in answer


def test_authorization_filters_farm_before_reading_cabinet(monkeypatch):
    class DB:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,query,params):
            assert 'farm_id=ANY(%s)' in query
            device,farms=params
            self.row={'device_id':'own'} if device=='own' and farms==['my_farm'] else None
            return self
        def fetchone(self):return self.row
    monkeypatch.setattr(store,'connect',DB)
    user={'farms':[{'farm_id':'my_farm','can_read':True},{'farm_id':'other_farm','can_read':False}]}
    assert store.authorize_device(user,'own')['device_id']=='own'
    with pytest.raises(HTTPException) as error:store.authorize_device(user,'other_cabinet')
    assert error.value.status_code==403

def fixture_events(hours=73):
    """Clock-controlled unit input ONLY: never publish these rows to the application."""
    rows=[]
    for index in range(int(hours*6)+1):
        when=BASE+timedelta(minutes=index*10)
        for group,values in [('sensor_readings',{'soil_moisture':62+5*math.sin(index/24),'temperature':26+3*math.sin(index/24),'ec':1.6+.1*math.sin(index/24),'ph':6+.15*math.sin(index/24),'quality':'good'}),
          ('device_status',{'pump_running':bool(index%12<6),'pressure':3,'pump_current':4,'supply_voltage':24,'packet_loss_rate':.01}),
          ('incident_ground_truth',{'power_loss':None,'mqtt_loss':None,'no_flow':None,'leak':None,'sensor_fault':None,'irrigation_abort':None,'ground_truth_origin':'synthetic_latent_incident'})]:
            rows.append({'id':len(rows)+1,'group_name':group,'observed_at':when.isoformat(),'received_at':when.isoformat(),
              'payload':{**values,'source':'UNIT_TEST_FIXTURE_ONLY','collection_version':VERSION,'acquisition_method':'mqtt_live'}})
        # A second status sample fills 5-minute coverage bins for this test fixture.
        if index<hours*6:
            at=when+timedelta(minutes=5)
            rows.append({'id':len(rows)+1,'group_name':'device_status','observed_at':at.isoformat(),'received_at':at.isoformat(),
              'payload':{'pump_running':False,'source':'UNIT_TEST_FIXTURE_ONLY','collection_version':VERSION,'acquisition_method':'mqtt_live'}})
    return rows


def test_backfilled_72h_is_not_elapsed_collection():
    rows=fixture_events()
    for row in rows:row['received_at']=(BASE+timedelta(hours=73)).isoformat()
    assert not acquisition_gate(rows,BASE+timedelta(hours=73))['eligible']
    for row in rows:row['payload']['backfill']=True
    assert acquisition_gate(rows)['eligible_sensor_rows']==0


@pytest.mark.parametrize('hours,expected',[(71,False),(72,True),(73,True)])
def test_actual_receipt_span_and_coverage_required(hours,expected):
    gate=acquisition_gate(fixture_events(hours),BASE+timedelta(hours=hours))
    assert gate['eligible']==expected


def test_long_span_with_large_gaps_still_fails():
    rows=fixture_events();rows=[r for r in rows if r['observed_at'] in [BASE.isoformat(),(BASE+timedelta(hours=73)).isoformat()]]
    assert not acquisition_gate(rows,BASE+timedelta(hours=73))['eligible']


def test_unversioned_history_does_not_count():
    rows=fixture_events()
    for row in rows:row['payload'].pop('collection_version')
    assert not acquisition_gate(rows,BASE+timedelta(hours=73))['eligible']


def test_fixed_cleaning_audits_invalid_future_duplicate_and_missing():
    row={'event_id':1,'customer_id':'a','device_id':'d','observed_at':BASE.isoformat(),'received_at':BASE.isoformat(),'soil_moisture':999,'ph':None}
    clean,audit=clean_group([row,row,{**row,'event_id':2,'observed_at':(BASE+timedelta(hours=1)).isoformat()}],'sensor_readings')
    assert len(clean)==1 and clean[0]['soil_moisture'] is None and clean[0]['ph'] is None
    assert audit['rejected_rows']==2 and not audit['learned_transforms_before_split']
    assert audit['changes'][0]['reason']=='invalid_physical_range_or_number'


@pytest.mark.parametrize('question,tool,zone,port',[
 ('Độ ẩm đất khu A giờ bao nhiêu?','sensor','zone_a',None),
 ('Hôm qua tưới mấy lần, tổng bao nhiêu phút?','irrigation',None,None),
 ('Van số 3 có đang chạy không?','operation',None,3),
 ('Tuần này khu B có ngày nào không tưới không?','irrigation','zone_b',None),
])
def test_four_questions_in_problem_b(question,tool,zone,port):
    plan=route(question)
    assert tool in plan['tools'] and plan['zone_id']==zone and plan['port']==port


def test_zone_b_never_receives_zone_a_value():
    answer=render_tool('sensor',{'items':[{'zone_id':'zone_a','soil_moisture':62}]},route('Độ ẩm khu B?'),'Độ ẩm khu B?',{'zones':[{'zone_id':'zone_a'}]})
    assert 'chưa cấu hình khu B' in answer and '62' not in answer


def test_port_role_and_unknown_port_cannot_use_general_valve_state():
    data={'items':[{'observed_at':datetime.now(timezone.utc).isoformat(),'valve_running':True,'outputs':[{'port':3,'role':'fertilizer_pump','running':False}]}]}
    answer=render_tool('operation',data,route('Van số 3 đang chạy không?'),'van',{})
    assert 'bơm phân' in answer and 'không được cấu hình là van' in answer and 'đang dừng' in answer
    answer=render_tool('operation',data,route('Van số 7 đang chạy không?'),'van',{})
    assert 'Chưa có trạng thái ngõ ra số 7' in answer


def test_irrigation_minutes_sum_has_source_and_incomplete_period_caveat():
    rows=[{'started_at':BASE.isoformat(),'ended_at':(BASE+timedelta(minutes=n)).isoformat(),'water_liters':20,'fertilizer_ml':10} for n in [10,20]]
    answer=render_tool('irrigation',{'items':rows},route('Hôm qua tưới mấy lần, tổng bao nhiêu phút?'),'hôm qua',{})
    assert '2 ca tưới' in answer and '30.0 phút' in answer and 'ca kết thúc trong kỳ' in answer


def test_no_run_log_does_not_prove_no_irrigation():
    answer=render_tool('irrigation',{'items':[]},route('Tuần này có ngày nào không tưới không?'),'tuần này',{})
    assert 'Không đồng nghĩa' in answer


def test_calibrated_pump_is_valid_without_meter_but_latch_blocks():
    status={'valve_running':True,'pump_running':True,'fertilizer_requested':True,'dosage_configured':True,'meter_configured':False,'calibration_valid':True,'calibrated_ml_per_min':24}
    assert fertilizer_reasons(status)==[]
    status['fertilizer_stop_latched']=True
    assert 'lệnh mới' in fertilizer_reasons(status)[0]


def test_simulated_sequence_has_water_and_fertilizer_interlocks():
    # runtime import requires paho, so the inference-service test image need not install it.
    import ast
    source=Path(__file__).parents[1]/'nextfarm_device/runtime.py'
    tree=ast.parse(source.read_text(encoding='utf-8'));node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='schedule_outputs')
    ns={};exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns);f=ns['schedule_outputs']
    assert f(0,True,True,False)=={'valve':True,'pump':False,'fertilizer':False}
    assert f(6,True,True,False)=={'valve':True,'pump':True,'fertilizer':False}
    assert all(f(11,True,True,False).values())
    assert f(1797,True,True,False)=={'valve':True,'pump':False,'fertilizer':False}
    assert not any(f(11,True,False,False).values())
    assert not any(f(11,True,True,True).values())


def test_future_status_cannot_claim_current_connected():
    now=datetime.now(timezone.utc)
    assert connectivity({'observed_at':(now+timedelta(hours=1)).isoformat()},now=now)['code']=='UNKNOWN'


def test_api_cannot_serve_historical_synthetic_registry(monkeypatch,tmp_path):
    monkeypatch.setattr(api,'MODELS',tmp_path/'device-v11')
    monkeypatch.setattr(store,'user_context',lambda _: {'role':'farmer'})
    monkeypatch.setattr(store,'authorize_device',lambda *_: {'data_origin':'synthetic'})
    result=TestClient(api.analytics_app()).get('/devices/a/predict',headers={'Authorization':'Bearer fixture'}).json()
    assert result['predictions']==[] and result['status']=='NOT_VALIDATED'
    assert api.model_reports()['ready_count']==0


def test_shared_model_training_keeps_unseen_customer_and_never_fakes_missing_labels(tmp_path):
    rows=fixture_events();gate=acquisition_gate(rows,BASE+timedelta(hours=73));assert gate['eligible']
    cabinets=[{'device_id':'device_'+x,'customer_id':'customer_'+x,'profile':{},'data_origin':'UNIT_TEST_FIXTURE_ONLY'} for x in 'abc']
    snapshot=tmp_path/'fixture-not-runtime';gates={c['device_id']:gate for c in cabinets}
    export_window(snapshot,cabinets,{c['device_id']:rows for c in cabinets},gates)
    report=train_snapshot(snapshot,tmp_path/'artifacts')
    assert report['ready_count']==0 and not report['production_ready']
    assert report['trained_count']==4 and len(report['models'])==10
    assert all(not m['trained'] for m in report['models'] if m['task']=='classification')
    run=tmp_path/'artifacts/runs'/snapshot.name;frame=pd.read_csv(run/'features_and_splits.csv')
    train=frame[frame.split=='train'];val=frame[frame.split=='validation'];test=frame[frame.split=='test_unseen_customer']
    assert set(test.customer_id).isdisjoint(set(train.customer_id)|set(val.customer_id))
    assert pd.to_datetime(train.label_end,utc=True).max()<pd.to_datetime(val.observed_at,utc=True).min()
    assert pd.to_datetime(val.label_end,utc=True).max()<pd.to_datetime(test.observed_at,utc=True).min()
    assert 'customer_id' not in report['features'] and 'device_id' not in report['features']
    assert len(list(run.glob('*_report.json')))==11
    assert (run/'training_report.html').exists()
    manifest=json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))
    first=snapshot/manifest['files'][0]['path'];first.write_text(first.read_text(encoding='utf-8')+'tampered',encoding='utf-8')
    with pytest.raises(ValueError,match='checksum'):seal_frame(snapshot)
