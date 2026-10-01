"""Safe default ML entrypoint.

Production mode requires an explicit dataset and never generates synthetic data.
The old synthetic suite remains available only behind --simulation-benchmark.
"""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

p=argparse.ArgumentParser()
p.add_argument('--dataset',help='Real/verified dataset folder for production-safe audit/training')
p.add_argument('--artifacts',default=None)
p.add_argument('--audit-only',action='store_true')
p.add_argument('--simulation-benchmark',action='store_true',help='Explicit legacy QA/research benchmark; NEVER production')
p.add_argument('--data',default='model-artifacts/data/device-v11')
p.add_argument('--generate',action='store_true')
p.add_argument('--days',type=int,default=42);p.add_argument('--sites',type=int,default=12);p.add_argument('--seed',type=int,default=20260910)
a=p.parse_args()

if a.simulation_benchmark:
    from nextfarm_device.simulation import generate_dataset
    from nextfarm_device.ml import train_suite
    if a.generate:
        if (Path(a.data)/'manifest.json').exists():p.error('Dataset already exists; choose a new version directory to preserve evidence')
        generate_dataset(a.data,a.sites,a.days,a.seed)
    r=train_suite(a.data,a.artifacts or 'model-artifacts/device-v11')
    print('SIMULATION BENCHMARK ONLY: READY',r['ready_count'],'/',r['model_count'],'production_ready=false')
else:
    if not a.dataset:
        p.error('--dataset is required for safe production training. Use --simulation-benchmark explicitly for legacy synthetic QA.')
    from nextfarm_device.production_training import run_production_pipeline
    project=Path(__file__).resolve().parents[1]
    r=run_production_pipeline(project,a.dataset,a.artifacts,allow_training=not a.audit_only)
    print('PRODUCTION-SAFE RUN',r['run_id'],'readiness='+r['readiness']['status'],'models='+str([(m['horizon_minutes'],m['status']) for m in r.get('models',[])]),'report='+str(r.get('docx_report')))
