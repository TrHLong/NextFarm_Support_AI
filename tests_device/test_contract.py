from datetime import datetime,timezone,timedelta
import numpy as np
import pandas as pd
from nextfarm_device.answers import route,connectivity,fertilizer_reasons,sensor_answer
from nextfarm_device.contracts import catalog,SPECS,RULE_CAPS
from nextfarm_device.ml import prepare_features,coverage
from nextfarm_device.store import period_bounds

def test_catalog_separates_10_trained_models_and_32_support_functions():
    assert len(SPECS)==10 and len(RULE_CAPS)==32
    items=catalog();assert len(items)==42
    assert all(x['status']==('BLOCKED' if x['kind']=='trained_model' else 'NO_DATA') for x in items)

def test_scope_readiness_requires_real_group_presence():
    values={x['key']:x for x in catalog(available_groups=['device_status'])}
    assert values['connection_status']['status']=='AVAILABLE'
    assert values['sensor_history']['status']=='NO_DATA'

def test_silence_does_not_prove_power_loss():
    now=datetime.now(timezone.utc)
    result=connectivity({'observed_at':(now-timedelta(minutes=5)).isoformat()},now=now)
    assert result['code']=='UNKNOWN' and 'mất điện hay lỗi MQTT' in result['text']

def test_independent_fresh_observer_distinguishes_two_faults():
    now=datetime.now(timezone.utc);s={'observed_at':now.isoformat()};obs={'observed_at':now.isoformat(),'power_confirmed':False,'mqtt_connected':False}
    assert connectivity(s,obs,now)['code']=='POWER_LOSS'
    obs['power_confirmed']=True
    assert connectivity(s,obs,now)['code']=='MQTT_INTERRUPTED'
    obs['observed_at']=(now-timedelta(minutes=10)).isoformat()
    assert connectivity(s,obs,now)['code']=='CONNECTED'

def test_natural_words_for_telemetry_silence():
    for q in ['Cảm biến câm','Tủ không gửi dữ liệu nữa','MQTT bị lỗi','Mất điện rồi','khong day du lieu']:
        assert 'connection' in route(q)['tools']

def test_multi_tool_scoped_device_question():
    plan=route('Độ ẩm tuần này thế nào và hôm nay tưới mấy lần?')
    assert 'sensor_history' in plan['tools'] and 'irrigation' in plan['tools']
    assert plan['confidence'] is None
    assert plan['tool_periods']['sensor_history']=='week' and plan['tool_periods']['irrigation']=='today'

def test_no_ticket_or_actuation_tool():
    assert route('Bật bơm ngay')['tools']==['read_only_policy']
    assert all('ticket' not in x for x in route('Cảm biến câm hãy tạo ticket')['tools'])

def test_fertilizer_interlock_explains_dosage_not_generic_offline():
    state={'pump_running':True,'valve_running':True,'fertilizer_requested':True,'dosage_configured':False,'meter_configured':True}
    assert fertilizer_reasons(state)==['chưa cấu hình định lượng']
    state['emergency_stop']=True
    assert 'dừng khẩn' in fertilizer_reasons(state)[0]

def test_question_value_distinguished_from_measured_value():
    now=datetime.now(timezone.utc)
    answer=sensor_answer({'items':[{'soil_moisture':59,'observed_at':now.isoformat(),'quality':'good'}]},'soil_moisture','Độ ẩm 62% có ổn?',{'thresholds':{'soil_moisture':[55,70]}},now)
    assert '59.000' in answer and 'bạn nhập 62' in answer and 'chưa xác minh' in answer

def test_future_values_cannot_change_past_features():
    times=pd.date_range('2026-01-01',periods=12,freq='10min',tz='UTC')
    sensor=pd.DataFrame({'observed_at':times,'soil_moisture':np.arange(12.)})
    status=pd.DataFrame({'observed_at':times,'pump_running':1})
    before,features=prepare_features(sensor,status)
    sensor.loc[9:,'soil_moisture']=9999
    after,_=prepare_features(sensor,status)
    pd.testing.assert_frame_equal(before.loc[:8,features],after.loc[:8,features])

def test_unknown_state_not_converted_to_offline_or_zero_loss():
    sensor=pd.DataFrame({'observed_at':['2026-01-01T00:10:00Z'],'soil_moisture':[62.]})
    status=pd.DataFrame({'observed_at':['2026-01-01T00:00:00Z'],'pump_running':[0],'packet_loss_rate':[0.]})
    frame,_=prepare_features(sensor,status)
    assert pd.isna(frame.pump_running.iloc[0]) and pd.isna(frame.packet_loss_rate.iloc[0])

def test_class_coverage_fails_before_training():
    _,ok=coverage(pd.DataFrame({'y':[0]*100}), 'y',5)
    assert not ok

def test_calendar_month_is_calendar_not_30_days():
    now=datetime(2026,9,9,tzinfo=timezone.utc)
    start,end=period_bounds('last_month',now)
    assert start.day==1 and start.month==8 and end.day==1 and end.month==9

def test_predict_question_restricts_models_to_requested_signal():
    assert route('Dự báo EC sau 30 phút')['model_names']==['ec_forecast']

def test_incomplete_counter_is_not_claimed_as_complete_water_total():
    from nextfarm_device.answers import render_tool
    answer=render_tool('irrigation',{'items':[{'water_liters':None,'fertilizer_ml':None,'counter_reset':True}]},{'period':'today'},'Tổng nước?',{})
    assert 'chưa đầy đủ' in answer and 'không xem thiếu là 0' in answer

def test_out_of_scope_tomorrow_question_is_not_an_irrigation_schedule():
    assert route('Giá vàng ngày mai thế nào?')['tools']==['out_of_scope']

def test_live_and_backfill_iso_timestamps_can_be_merged():
    sensor=pd.DataFrame({'observed_at':['2026-09-10T07:00:00+07:00','2026-09-10T07:10:00.123456+07:00'],'soil_moisture':[60,61]})
    status=pd.DataFrame({'observed_at':['2026-09-10T00:00:00Z','2026-09-10T00:10:00Z'],'pump_running':[False,True]})
    frame,_=prepare_features(sensor,status)
    assert frame.pump_running.tolist()==[False,True]

def test_rejected_retraining_cannot_replace_working_registry(tmp_path):
    import json
    from nextfarm_device.ml import publish_registry
    before={'dataset_version':'accepted','models':{'working':{'sha256':'preserved'}}}
    (tmp_path/'active_models.json').write_text(json.dumps(before))
    report={'dataset_version':'rejected','ready_count':0}
    result=publish_registry(tmp_path,report,{})
    assert result['promoted'] is False
    assert json.loads((tmp_path/'active_models.json').read_text())==before
    assert json.loads((tmp_path/'latest_candidate_report.json').read_text())['dataset_version']=='rejected'
