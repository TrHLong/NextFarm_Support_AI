"""Fixed, auditable data checks. Never learn imputation parameters here."""
import math
from datetime import datetime

CLEANING_VERSION='problem_b_clean_v2'
NULL_WORDS={'','null','none','nan','na','n/a','nat','undefined','unknown'}
SENSOR_BOUNDS={'soil_moisture':(0,100),'air_humidity':(0,100),'temperature':(-50,100),'ec':(0,100),'ph':(0,14),'flow_rate':(0,10000)}
STATUS_BOUNDS={'flow_rate':(0,10000),'pressure':(0,100),'pump_current':(0,1000),'sensor_bus_errors':(0,None),'supply_voltage':(0,1000),'rssi':(-200,20),'packet_loss_rate':(0,1),'command_failure_rate':(0,1),'calibrated_ml_per_min':(0,1000000)}
STATUS_FLAGS=['pump_running','valve_running','fertilizer_running','fertilizer_requested','dosage_configured','meter_configured','calibration_valid','emergency_stop','fertilizer_stop_latched','online']
TRUTH_FIELDS=['power_loss','mqtt_loss','no_flow','leak','sensor_fault','irrigation_abort']
RUN_BOUNDS={'water_liters':(0,None),'fertilizer_ml':(0,None),'duration_minutes':(0,None)}


def missing(value):
    return value is None or (isinstance(value,str) and value.strip().lower() in NULL_WORDS) or (isinstance(value,float) and math.isnan(value))


def expected_fields(group):
    return {'sensor_readings':list(SENSOR_BOUNDS), 'device_status':list(STATUS_BOUNDS)+STATUS_FLAGS,
            'incident_ground_truth':TRUTH_FIELDS+['ground_truth_origin'],
            'irrigation_runs':list(RUN_BOUNDS)+['started_at','ended_at','volume_valid','counter_reset'],
            'connection_observer':['power_confirmed','mqtt_connected']}.get(group,[])


def missing_counts(rows,fields):
    return {key:sum(missing(row.get(key)) for row in rows) for key in fields}


def normalize_values(row,group):
    row=dict(row);changes=[]
    def changed(key,value,reason):
        original=row.get(key);row[key]=value
        changes.append({'event_id':row.get('event_id'),'field':key,'reason':reason,'original':str(original),'cleaned':value})
    for key,value in list(row.items()):
        if isinstance(value,str) and missing(value):changed(key,None,'empty_token_to_null')
    bounds={'sensor_readings':SENSOR_BOUNDS,'device_status':STATUS_BOUNDS,'irrigation_runs':RUN_BOUNDS}.get(group,{})
    for key,(lo,hi) in bounds.items():
        value=row.get(key)
        if missing(value):row[key]=None;continue
        try:
            if isinstance(value,bool):raise ValueError('Boolean is not a physical measurement')
            number=float(value.strip().replace(',','.')) if isinstance(value,str) else float(value)
            if not math.isfinite(number) or number<lo or (hi is not None and number>hi):raise ValueError()
            row[key]=number
            if isinstance(value,str):changes.append({'event_id':row.get('event_id'),'field':key,'reason':'numeric_text_to_number','original':value,'cleaned':number})
        except (ValueError,TypeError):changed(key,None,'invalid_physical_range_or_number')
    flags={'device_status':STATUS_FLAGS,'irrigation_runs':['volume_valid','counter_reset'],'connection_observer':['power_confirmed','mqtt_connected'],'incident_ground_truth':TRUTH_FIELDS}.get(group,[])
    for key in flags:
        value=row.get(key)
        if missing(value):row[key]=None;continue
        text=str(value).strip().lower()
        parsed=True if text in ['true','1','1.0'] else False if text in ['false','0','0.0'] else None
        if parsed is None:changed(key,None,'invalid_binary_value')
        else:
            row[key]=int(parsed) if group=='incident_ground_truth' else parsed
            if isinstance(value,str):changes.append({'event_id':row.get('event_id'),'field':key,'reason':'binary_text_normalized','original':value,'cleaned':row[key]})
    if group=='sensor_readings' and str(row.get('quality','')).strip().lower() in ['bad','suspect']:
        for key in SENSOR_BOUNDS:row[key]=None
        changes.append({'event_id':row.get('event_id'),'reason':'sensor_quality_masked_for_ml'})
    if group=='irrigation_runs':
        if row.get('counter_reset') is True or row.get('volume_valid') is False:
            for key in ['water_liters','fertilizer_ml']:
                if not missing(row.get(key)):changed(key,None,'untrusted_or_reset_counter')
        times=[]
        for key in ['started_at','ended_at']:
            value=row.get(key)
            if missing(value):row[key]=None;times.append(None);continue
            try:
                stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
                if stamp.tzinfo is None:raise ValueError()
                times.append(stamp)
            except (ValueError,TypeError):changed(key,None,'invalid_run_timestamp');times.append(None)
        start,end=times
        if start and end and end>=start:
            minutes=(end-start).total_seconds()/60
            if row.get('duration_minutes')!=minutes:changed('duration_minutes',minutes,'duration_from_verified_endpoints')
        else:
            if row.get('duration_minutes') is not None:changed('duration_minutes',None,'missing_or_reversed_run_endpoints')
    return row,changes
