"""Retraining entrypoint. Simulation is explicit; production must go through train_production_safe.py readiness gate."""
import argparse,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('--scope',choices=['simulation','production'],required=True);p.add_argument('--dataset');a=p.parse_args()
if a.scope=='simulation':
 raise SystemExit(subprocess.call([sys.executable,'scripts/build_v103_simulation_models.py']))
if not a.dataset: raise SystemExit('--dataset bắt buộc cho production')
raise SystemExit(subprocess.call([sys.executable,'scripts/train_production_safe.py','--dataset',a.dataset]))
