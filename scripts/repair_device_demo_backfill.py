"""Correct only the explicitly synthetic v11 backfill, preserving previous rows for audit."""
import json,hashlib,sys,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nextfarm_device import store
from nextfarm_device.simulation import generate_site
from nextfarm_device.runtime import clean
from psycopg.types.json import Jsonb

def repair(output):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True);before=[];changes=[]
    with store.connect() as db:
        cabinets=db.execute("SELECT device_id FROM device_db.cabinets WHERE data_origin='synthetic_device_spec_v11' ORDER BY device_id").fetchall()
        for index,cab in enumerate(cabinets):
            device=cab['device_id']
            end=db.execute("SELECT max(observed_at) AS value FROM device_db.events WHERE device_id=%s AND group_name='incident_ground_truth' AND payload->>'backfill'='true'",(device,)).fetchone()['value']
            if end is None:continue
            frames=generate_site(index+100,days=3,end=end.isoformat())
            for group,frame in zip(['sensor_readings','device_status','incident_ground_truth','irrigation_runs','control_commands','incidents'],frames):
                for _,row in frame.iterrows():
                    payload=clean(row.to_dict());stamp=payload.get('observed_at',payload.get('ended_at',payload.get('requested_at',payload.get('started_at'))))
                    payload.update(source='synthetic_device_spec_v11',backfill=True)
                    existing=db.execute("SELECT id,payload FROM device_db.events WHERE device_id=%s AND group_name=%s AND observed_at=%s AND payload->>'backfill'='true'",(device,group,stamp)).fetchone()
                    if not existing or existing['payload']==payload:continue
                    before.append({'id':existing['id'],'device_id':device,'group':group,'payload':existing['payload']})
                    db.execute('UPDATE device_db.events SET payload=%s WHERE id=%s',(Jsonb(payload),existing['id']))
                    changes.append({'id':existing['id'],'device_id':device,'group':group})
        # Save audit inside transaction; no commit if audit write fails.
        if changes:
            if output.exists():raise RuntimeError('Audit file already exists; choose a new filename')
            output.write_text(json.dumps({'reason':'MQTT interruptions retain local schedules; power cut invalidates counters; physical pump interruption reflected in flow','before':before,'changes':changes},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Synthetic backfill records corrected:',len(changes))

if __name__=='__main__':repair(sys.argv[1])
