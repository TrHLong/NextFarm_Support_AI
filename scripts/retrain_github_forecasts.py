"""Relocate immutable input metadata for a cloned repository, then run real training."""
import argparse,hashlib,json,sys
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def prepare():
    package=json.loads((ROOT/'GITHUB_PACKAGE_MANIFEST.json').read_text(encoding='utf-8'));runs=package['frozen_runs']
    history=ROOT/'model-artifacts/historical-customer'/runs['historical']/'training_report.json'
    benchmark=ROOT/'model-artifacts/benchmark-retrain'/runs['benchmark']/'training_report.json'
    feature=ROOT/'model-artifacts/data/historical-customer'/runs['historical']/'features_with_split.csv'
    metadata=json.loads(history.read_text(encoding='utf-8'))
    if sha(feature)!=metadata['feature_csv']['sha256']:raise ValueError('Feature CSV changed: refuse to claim a sealed-input re-run')
    bridge=ROOT/'github-local-inputs'
    relocated=bridge/'model-artifacts/historical-customer/input_report.json'
    metadata['feature_csv']['path']=str(feature)
    metadata['packaging_relocation']={'original_report':str(history),'original_sha256':sha(history),'reason':'Only input paths relocated; original report and feature bytes unchanged.'}
    write(relocated,metadata)
    write(relocated.parent/'latest_report.json',{'run_id':runs['historical'],'report_path':str(relocated)})
    write(bridge/'model-artifacts/benchmark-retrain/latest_report.json',{'run_id':runs['benchmark'],'report_path':str(benchmark)})
    print(json.dumps({'input_feature_csv':str(feature),'sha256_verified':True,'historical_scope':'reused synthetic historical test; not new blind evaluation'}))
    return bridge

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare-only',action='store_true');a=p.parse_args();bridge=prepare()
    if not a.prepare_only:
        from nextfarm_device.refine_forecasts import run
        run(bridge,ROOT/'model-artifacts/github-retrains')
