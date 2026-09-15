"""Per-device 72h acquisition, immutable CSV and real estimator training."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import threading,logging,json
from . import store
from .collection import VERSION,acquisition_gate,export_window
from .ml import write_json

def auto_tick(model_root):
    root=Path(model_root).parent/'problem-b';root.mkdir(parents=True,exist_ok=True)
    path=root/'collection_state.json';now=datetime.now(timezone.utc)
    with store.connect() as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        cabinets=db.execute('SELECT * FROM device_db.cabinets ORDER BY device_id').fetchall()
        # Poll only coverage samples. Full 5-second status rows are exported once due,
        # not repeatedly loaded into Python every five minutes.
        rows=db.execute("""SELECT DISTINCT ON (device_id,group_name,date_bin(interval '5 minutes',observed_at,timestamptz '2000-01-01'))
          id,device_id,group_name,observed_at,received_at,payload
          FROM device_db.events WHERE received_at>=now()-interval '4 days'
          AND payload->>'collection_version'=%s AND group_name IN ('sensor_readings','device_status')
          ORDER BY device_id,group_name,date_bin(interval '5 minutes',observed_at,timestamptz '2000-01-01'),received_at,id""",(VERSION,)).fetchall()
    events={c['device_id']:[] for c in cabinets}
    for row in rows:
        if row['device_id'] in events:events[row['device_id']].append(row)
    gates={device:acquisition_gate(values,now) for device,values in events.items()}
    old=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    state={'contract':VERSION,'updated_at':now.isoformat(),'automatic':True,'required_acquisition_hours':72,'status':'COLLECTING_72H',
        'devices':gates,'training_from_chat':False,'backfill_counted':False,'last_snapshot':old.get('last_snapshot'),
        'last_export_at':old.get('last_export_at'),'reasons':[],'source':'MQTT live simulator; not NextFarm field data'}
    if any(g['eligible'] for g in gates.values()):
        due=not old.get('last_export_at') or now-datetime.fromisoformat(old['last_export_at'])>=timedelta(hours=24)
        if due:
            with store.connect() as db:
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                for device,gate in gates.items():
                    if not gate['eligible']:continue
                    events[device]=db.execute("""SELECT id,device_id,group_name,observed_at,received_at,payload FROM device_db.events
                      WHERE device_id=%s AND received_at<=%s AND
                      ((observed_at>=%s AND observed_at<%s AND payload->>'collection_version'=%s) OR group_name='irrigation_schedules')
                      ORDER BY observed_at,id""",(device,gate['window_end'],gate['window_start'],gate['window_end'],VERSION)).fetchall()
            folder=root.parent/'data'/'problem-b-runtime'/('capture-'+now.strftime('%Y%m%dT%H%M%SZ'))
            export_window(folder,cabinets,events,gates);state.update(status='CSV_EXPORTED',last_snapshot=str(folder),last_export_at=now.isoformat())
            from .runtime_training import train_snapshot
            trained=train_snapshot(folder,root);state.update(status=trained['status'],trained_count=trained.get('trained_count',0),training_report=str(root/'latest_training_report.json'))
        else:state['status']='WAITING_NEXT_24H_EXPORT'
    else:state['reasons']=['Chưa tủ nào đạt đủ 72 giờ thu nhận và độ phủ; chưa xuất bộ CSV để train. Snapshot cũ chỉ là lịch sử kiểm thử.']
    write_json(path,state);return state

def start_worker(root,stop):
    def work():
        while not stop.is_set():
            try:auto_tick(root)
            except Exception as exc:
                logging.exception('Problem B collection worker')
                error={'at':datetime.now(timezone.utc).isoformat(),'error':type(exc).__name__,'status':'COLLECTION_ERROR','required_acquisition_hours':72,'devices':{},'automatic':True}
                write_json(Path(root).parent/'problem-b/collection_error.json',error)
                write_json(Path(root).parent/'problem-b/collection_state.json',error)
            stop.wait(300)
    thread=threading.Thread(target=work,daemon=True);thread.start();return thread
