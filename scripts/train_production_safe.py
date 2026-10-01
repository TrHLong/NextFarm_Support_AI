import argparse,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nextfarm_device.production_training import run_production_pipeline

p=argparse.ArgumentParser(description='NextFarm production-safe data audit + conditional training')
p.add_argument('--project',default=str(Path(__file__).resolve().parents[1]))
p.add_argument('--dataset',required=True,help='Folder containing sensor_readings.(parquet/csv/jsonl) and optional event tables')
p.add_argument('--artifacts',default=None)
p.add_argument('--audit-only',action='store_true',help='Run ingestion/audit/readiness/report without training')
a=p.parse_args()
r=run_production_pipeline(a.project,a.dataset,a.artifacts,allow_training=not a.audit_only)
print(json.dumps({'run_id':r['run_id'],'readiness':r['readiness']['status'],'models':[(m['horizon_minutes'],m['status']) for m in r.get('models',[])],'report':r.get('docx_report')},ensure_ascii=False,indent=2))
