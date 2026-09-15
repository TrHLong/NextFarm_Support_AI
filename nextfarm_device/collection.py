"""Audited 72-hour acquisition contract. Historical backfill never earns elapsed time."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import csv,json,hashlib,math
from .contracts import GROUPS
from .data_quality import CLEANING_VERSION,expected_fields,missing,missing_counts,normalize_values

VERSION='problem_b_v12'
HOURS=72
SIGNALS={'soil_moisture':(0,100),'air_humidity':(0,100),'temperature':(-50,100),
         'ec':(0,100),'ph':(0,14),'flow_rate':(0,10000)}
META=['event_id','customer_id','device_id','observed_at','received_at','source','collection_version','acquisition_method']

def stamp(x):
    d=datetime.fromisoformat(str(x).replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('Timestamp needs timezone')
    return d.astimezone(timezone.utc)

def eligible_event(event):
    payload=event.get('payload',event)
    if payload.get('backfill') or payload.get('collection_version')!=VERSION:return False
    return payload.get('acquisition_method') in ['mqtt_live','server_observer','configuration_snapshot','verified_incident_annotation']

def acquisition_gate(rows,now=None):
    """Called per cabinet. Counts describe sampling coverage, not independent examples."""
    now=now or datetime.now(timezone.utc)
    sensor=[r for r in rows if r['group_name']=='sensor_readings' and eligible_event(r)]
    status=[r for r in rows if r['group_name']=='device_status' and eligible_event(r)]
    result={'contract':VERSION,'required_hours':HOURS,'eligible_sensor_rows':len(sensor),'eligible_status_rows':len(status),
            'elapsed_received_hours':0,'eligible':False,'reasons':[]}
    if not sensor or not status:
        result['reasons']=['Chưa có đủ hai luồng sensor và trạng thái thu trực tiếp theo hợp đồng 72 giờ'];return result
    first=max(min(stamp(r['received_at']) for r in sensor),min(stamp(r['received_at']) for r in status))
    last=min(max(stamp(r['received_at']) for r in sensor),max(stamp(r['received_at']) for r in status))
    result.update(first_received=first.isoformat(),last_received=last.isoformat(),elapsed_received_hours=max(0,(last-first).total_seconds()/3600))
    if last-first<timedelta(hours=HOURS):result['reasons'].append('Chưa thu đủ 72 giờ theo thời gian server nhận; không tính mốc giờ sinh bù')
    start=last-timedelta(hours=HOURS);result.update(window_start=start.isoformat(),window_end=last.isoformat())
    for name,values,seconds in [('sensor',sensor,600),('status',status,300)]:
        # Status coverage checks 5-minute windows; does not pretend missing 5-second packets arrived.
        filtered=[r for r in values if start<=stamp(r['observed_at'])<last and start<=stamp(r['received_at'])<=last]
        bins={int((stamp(r['observed_at'])-start).total_seconds()//seconds) for r in filtered}
        expected=HOURS*3600//seconds;ratio=len(bins)/expected
        result[name+'_coverage']=round(ratio,6);result[name+'_expected_bins']=expected
        if ratio<.9:result['reasons'].append(f'{name}: chỉ {len(bins)}/{expected} khoảng có dữ liệu; yêu cầu phủ ít nhất 90% trước xử lý ML')
    if now-last>timedelta(minutes=30):result['reasons'].append('Dữ liệu cuối đã trễ hơn 30 phút')
    if last>now+timedelta(seconds=30):result['reasons'].append('Thời gian server nhận nằm trong tương lai; chưa đủ bằng chứng thu nhận')
    result['eligible']=not result['reasons'];return result

def flatten(row,customer,device):
    return {**row['payload'],'event_id':row['id'],'customer_id':customer,'device_id':device,
       'observed_at':stamp(row['observed_at']).isoformat(),'received_at':stamp(row['received_at']).isoformat()}

def save_csv(path,rows):
    keys=list(dict.fromkeys(META+[k for r in rows for k in r]));path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,keys);writer.writeheader()
        for row in rows:writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    return {'path':path.name,'rows':len(rows),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def clean_group(rows,group):
    """Fixed validation before splitting. No learned imputation/scaling on whole dataset."""
    clean=[];rejected=[];changes=[];seen=set()
    fields=list(dict.fromkeys(META+expected_fields(group)+[key for row in rows for key in row]))
    before=missing_counts(rows,fields)
    for item in rows:
        row=dict(item);issues=[]
        try:
            observed=stamp(row['observed_at']);received=stamp(row['received_at'])
            if observed>received+timedelta(seconds=30):issues.append('future_timestamp')
            if missing(row.get('customer_id')) or missing(row.get('device_id')):issues.append('missing_owner')
            if missing(row.get('event_id')):issues.append('missing_event_id')
            key=(row.get('device_id'),row.get('event_id'))
            if key in seen:issues.append('duplicate_event_id')
            seen.add(key)
        except (ValueError,TypeError,KeyError):issues.append('invalid_timestamp')
        if issues:rejected.append({**row,'rejection_reasons':issues});continue
        row,edits=normalize_values(row,group);changes.extend(edits)
        clean.append(row)
    clean.sort(key=lambda r:(r['device_id'],stamp(r['observed_at']),str(r['event_id'])))
    return clean,{'input_rows':len(rows),'accepted_rows':len(clean),'rejected_rows':len(rejected),'rejected':rejected,'changes':changes,
        'cleaning_version':CLEANING_VERSION,'missing_before':before,'missing_after':missing_counts(clean,fields),
        'learned_transforms_before_split':False,'missing_policy':'NaN retained; median/imputer/scaler fit train only; missing labels never filled'}

def export_window(out,cabinets,events,gates):
    """Immutable raw and cleaned files for each qualifying customer/device only."""
    out=Path(out)
    if out.exists():raise ValueError('Snapshot path already exists')
    out.mkdir(parents=True);files=[];audits={};profiles=[]
    for cab in cabinets:
        gate=gates[cab['device_id']]
        if not gate['eligible']:continue
        start,end=stamp(gate['window_start']),stamp(gate['window_end'])
        customer,device=cab['customer_id'],cab['device_id'];values=events[device]
        for group in GROUPS+['incident_ground_truth','connection_observer','technical_logs']:
            if group=='device_profile':
                rows=[{'event_id':'profile:'+device,'customer_id':customer,'device_id':device,'observed_at':end.isoformat(),'received_at':end.isoformat(),'profile':cab['profile'],'source':cab['data_origin'],'collection_version':VERSION,'acquisition_method':'configuration_snapshot'}]
            elif group=='irrigation_schedules':
                candidates=[r for r in values if r['group_name']==group and stamp(r['received_at'])<=end]
                latest={}
                for r in sorted(candidates,key=lambda x:stamp(x['observed_at'])):latest[r['payload'].get('name',str(r['id']))]=r
                rows=[flatten(r,customer,device) for r in latest.values()]
            else:rows=[flatten(r,customer,device) for r in values if r['group_name']==group and eligible_event(r) and start<=stamp(r['observed_at'])<end and stamp(r['received_at'])<=end]
            rel=Path('customers')/customer/device/(group+'.csv')
            raw=save_csv(out/'raw'/rel,rows);processed,audit=clean_group(rows,group);cleaned=save_csv(out/'cleaned'/rel,processed)
            for kind,record in [('raw',raw),('cleaned',cleaned)]:files.append({**record,'path':str(Path(kind)/rel),'group':group,'customer_id':customer,'device_id':device,'stage':kind})
            audits[device+':'+group]=audit
        profiles.append({'customer_id':customer,'device_id':device,'source':cab['data_origin']})
    manifest={'contract':VERSION,'dataset_version':out.name,'created_at':datetime.now(timezone.utc).isoformat(),'acquisition_hours':72,
        'cleaning_version':CLEANING_VERSION,
        'source':'runtime_capture','data_sources':profiles,'backfill_allowed':False,'chat_used':False,'gates':gates,'files':files,
        'processing_order':['raw_csv','fixed_schema_and_physical_checks','causal_features','time_and_customer_split','fit_transforms_on_train','fit_model','validation_selection','locked_test','export_candidate'],
        'live_simulator_is_field_data':False}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'cleaning_report.json').write_text(json.dumps(audits,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest
