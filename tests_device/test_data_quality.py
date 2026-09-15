from datetime import datetime,timezone,timedelta
from nextfarm_device.collection import clean_group
from nextfarm_device.data_quality import CLEANING_VERSION

NOW=datetime(2026,9,13,tzinfo=timezone.utc)
def row(**values):return {'event_id':1,'customer_id':'customer_a','device_id':'cabinet_a','observed_at':NOW.isoformat(),'received_at':NOW.isoformat(),**values}

def test_empty_tokens_keep_unknown_and_are_counted():
    cleaned,audit=clean_group([row(soil_moisture='  ',temperature='NULL',ec='NaN',ph=None)],'sensor_readings')
    assert all(cleaned[0][k] is None for k in ['soil_moisture','temperature','ec','ph'])
    assert audit['missing_before']['temperature']==1 and audit['missing_after']['temperature']==1
    assert audit['cleaning_version']==CLEANING_VERSION

def test_status_invalid_numbers_and_unknown_flags_never_become_zero():
    cleaned,audit=clean_group([row(supply_voltage='inf',packet_loss_rate=5,pump_running='unknown',valve_running='False',fertilizer_running='1')],'device_status')
    r=cleaned[0]
    assert r['supply_voltage'] is None and r['packet_loss_rate'] is None and r['pump_running'] is None
    assert r['valve_running'] is False and r['fertilizer_running'] is True
    assert audit['missing_after']['supply_voltage']==1

def test_truth_binary_validation_preserves_missing_labels():
    cleaned,_=clean_group([row(power_loss=2,mqtt_loss='',sensor_fault='0',leak='1')],'incident_ground_truth')
    assert cleaned[0]['power_loss'] is None and cleaned[0]['mqtt_loss'] is None
    assert cleaned[0]['sensor_fault']==0 and cleaned[0]['leak']==1
    assert cleaned[0]['no_flow'] is None

def test_reset_counter_and_reversed_duration_are_not_used():
    cleaned,audit=clean_group([row(water_liters=123,fertilizer_ml=10,counter_reset='True',volume_valid=True,duration_minutes=20,started_at=NOW.isoformat(),ended_at=(NOW-timedelta(minutes=1)).isoformat())],'irrigation_runs')
    assert all(cleaned[0][k] is None for k in ['water_liters','fertilizer_ml','duration_minutes'])
    assert any(c['reason']=='untrusted_or_reset_counter' for c in audit['changes'])

def test_missing_id_or_blank_customer_is_rejected():
    clean,audit=clean_group([row(event_id=None),row(event_id=2,customer_id='  ')],'sensor_readings')
    assert clean==[] and audit['rejected_rows']==2

def test_valid_numeric_zero_survives_cleaning():
    clean,_=clean_group([row(flow_rate='0',soil_moisture=0,temperature=-2.0)],'sensor_readings')
    assert clean[0]['flow_rate']==0 and clean[0]['soil_moisture']==0 and clean[0]['temperature']==-2
