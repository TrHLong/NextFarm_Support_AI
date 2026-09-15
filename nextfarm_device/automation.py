"""Automatic CSV export and candidate training with explicit eligibility gates.

The existing benchmark remains immutable. Runtime windows are a separate dataset
version. Missing ground truth blocks training; chat feedback is never a label.
"""
from pathlib import Path
from datetime import datetime,timezone
import threading,time,json,hashlib,logging
from . import store
CONTRACT='v11-profile-csv-and-full-suite-promotion'

def export_runtime(root):
    import pandas as pd
    run='runtime-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');out=Path(root)/run
    out.mkdir(parents=True,exist_ok=True);files=[]
    with store.connect() as db:
        cabinets=db.execute('SELECT * FROM device_db.cabinets ORDER BY device_id').fetchall()
        for cabinet in cabinets:
            folder=out/'customers'/cabinet['customer_id'];folder.mkdir(parents=True,exist_ok=True)
            for group in ['sensor_readings','device_status','irrigation_schedules','irrigation_runs','control_commands','alerts','incident_ground_truth']:
                rows=db.execute("SELECT payload,observed_at FROM device_db.events WHERE device_id=%s AND group_name=%s AND observed_at>=now()-interval '42 days' ORDER BY observed_at",(cabinet['device_id'],group)).fetchall()
                values=[{**row['payload'],'customer_id':cabinet['customer_id'],'device_id':cabinet['device_id'],'observed_at':row['observed_at'].isoformat()} for row in rows]
                # One file per cabinet avoids collisions for customers with several cabinets.
                name=f'{cabinet["device_id"]}_{group}.csv';path=folder/name
                pd.DataFrame(values).to_csv(path,index=False)
                files.append({'customer_id':cabinet['customer_id'],'device_id':cabinet['device_id'],'group':group,'rows':len(values),'path':str(path.relative_to(out)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            (folder/(cabinet['device_id']+'_device_profile.json')).write_text(json.dumps(cabinet,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
            profile_path=folder/(cabinet['device_id']+'_device_profile.csv')
            pd.DataFrame([{**cabinet,'profile':json.dumps(cabinet['profile'],ensure_ascii=False)}]).to_csv(profile_path,index=False)
            files.append({'customer_id':cabinet['customer_id'],'device_id':cabinet['device_id'],'group':'device_profile','rows':1,'path':str(profile_path.relative_to(out)),'sha256':hashlib.sha256(profile_path.read_bytes()).hexdigest()})
    manifest={'dataset_version':run,'created_at':datetime.now(timezone.utc).isoformat(),'source':'runtime_device_csv',
       'files':files,'chat_used':False,'customer_id_is_feature':False,'status':'SNAPSHOT_EXPORTED',
       'policy':'Separate customer/cabinet files. Independently annotated incidents required before candidate training.'}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest,out

def auto_tick(model_root):
    from .ml import write_json
    model_root=Path(model_root);state_file=model_root/'automation_state.json'
    old=json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
    with store.connect() as db:
        rows=db.execute("SELECT device_id,group_name,count(*) AS rows,min(observed_at) AS first,max(observed_at) AS last FROM device_db.events GROUP BY device_id,group_name").fetchall()
    counts={r['device_id']+':'+r['group_name']:int(r['rows']) for r in rows}
    sensor_new=sum(max(0,n-old.get('watermark',{}).get(k,0)) for k,n in counts.items() if k.endswith(':sensor_readings'))
    if old.get('contract')==CONTRACT and sensor_new<144:return old
    manifest,snapshot=export_runtime(model_root.parent/'data'/'device-runtime')
    reasons=[];devices={r['device_id'] for r in rows if r['group_name']=='sensor_readings'}
    for device in devices:
        for group,minimum in [('sensor_readings',2016),('device_status',2016),('irrigation_runs',20),('control_commands',20),('incident_ground_truth',2016)]:
            row=next((r for r in rows if r['device_id']==device and r['group_name']==group),None)
            if not row or row['rows']<minimum:reasons.append(f'{device}/{group}: cần >= {minimum} dòng và nhãn độc lập')
        sensor=next(r for r in rows if r['device_id']==device and r['group_name']=='sensor_readings')
        if (sensor['last']-sensor['first']).total_seconds()<14*86400:reasons.append(device+': cần >=14 ngày thời gian quan sát')
    # Do not promote a field customer using synthetic benchmark certification.
    with store.connect() as db:customers=db.execute('SELECT DISTINCT customer_id,data_origin FROM device_db.cabinets').fetchall()
    if len(customers)<9:reasons.append('Cần >=9 khách hàng riêng biệt cho train/validation/held-out; nhiều tủ cùng khách không tính thêm khách hàng')
    if any(x['data_origin']!='synthetic_device_spec_v11' for x in customers):reasons.append('Dữ liệu thật cần incident ground truth đã duyệt và kiểm định thực địa riêng')
    state={'contract':CONTRACT,'last_snapshot':str(snapshot),'watermark':counts,'status':'BLOCKED' if reasons else 'ELIGIBLE',
        'reasons':reasons,'automatic':True,'chat_used':False,'updated_at':datetime.now(timezone.utc).isoformat()}
    if not reasons:
        # Normalize per-cabinet files into datasets without merging trajectories.
        import pandas as pd
        from .ml import train_suite
        pool=snapshot/'training';pool.mkdir()
        records=[];observed_spans=[]
        for c in customers:
            # Current contract requires one cabinet trajectory per dataset site;
            # use the longest recorded cabinet for each customer, declare selection.
            matching=[x for x in manifest['files'] if x['customer_id']==c['customer_id'] and x['group']=='sensor_readings']
            selected=max(matching,key=lambda x:x['rows'])['device_id']
            target=pool/'customers'/c['customer_id'];target.mkdir(parents=True)
            for group in ['sensor_readings','device_status','incident_ground_truth']:
                source=next(x for x in manifest['files'] if x['device_id']==selected and x['group']==group)
                path=target/(group+'.csv');path.write_bytes((snapshot/source['path']).read_bytes());records.append({'path':str(path.relative_to(pool)),'rows':source['rows'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
                if group=='sensor_readings':
                    times=pd.to_datetime(pd.read_csv(path,usecols=['observed_at']).observed_at,utc=True,format='ISO8601');observed_spans.append((times.max()-times.min()).total_seconds()/86400)
        write_json(pool/'manifest.json',{'source':'synthetic_device_spec_v11','files':records,'days':max(observed_spans),'window_limit_days':42,'customer_selection':'longest cabinet per customer, identities retained'})
        result=train_suite(pool,model_root);state.update(status='TRAINED' if result['deployment']['promoted'] else 'CANDIDATE_REJECTED',dataset_version=result['dataset_version'],ready_count=result['ready_count'],deployment=result['deployment'])
    write_json(state_file,state);return state

def start_worker(root,stop):
    def run():
        while not stop.is_set():
            try:auto_tick(root)
            except Exception as exc:
                logging.exception('automatic device ML')
                from .ml import write_json
                write_json(Path(root)/'automation_error.json',{'error':str(exc),'at':datetime.now(timezone.utc).isoformat()})
            stop.wait(300)
    t=threading.Thread(target=run,daemon=True);t.start();return t
