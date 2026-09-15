import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nextfarm_device.simulation import generate_dataset
from nextfarm_device.ml import train_suite
p=argparse.ArgumentParser();p.add_argument('--data',default='model-artifacts/data/device-v11');p.add_argument('--artifacts',default='model-artifacts/device-v11');p.add_argument('--generate',action='store_true');p.add_argument('--days',type=int,default=42);p.add_argument('--sites',type=int,default=12);p.add_argument('--seed',type=int,default=20260910)
a=p.parse_args()
if a.generate:
    if (Path(a.data)/'manifest.json').exists():p.error('Dataset already exists; choose a new version directory to preserve evidence')
    generate_dataset(a.data,a.sites,a.days,a.seed)
r=train_suite(a.data,a.artifacts)
print('READY',r['ready_count'],'/',r['model_count'],'scope=simulation_only; production_ready=false')
