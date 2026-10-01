from __future__ import annotations
import importlib, json, os, shutil, sys, time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE))
from common import *
from report import generate

MODULES=['train_01_soil_moisture','train_02_nutrient','train_03_anomaly','train_04_irrigation','train_05_maintenance']

def serving_smoke(out_dir,models):
    # End-to-end equivalent of online inference in shadow mode, using packaged artifacts.
    raw=load_raw(); df=build_features(raw); _,_,te,_=temporal_customer_split(df); log=out_dir/'logs'/'inference-shadow.jsonl'; log.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    for m in models:
        import joblib
        art=joblib.load(m['artifact']); sample=te.dropna(subset=art['features']).iloc[0]; X=pd.DataFrame([{c:sample[c] for c in art['features']}])
        t=time.perf_counter(); pred=art['pipeline'].predict(X)[0]; latency=(time.perf_counter()-t)*1000
        rec={'timestamp':datetime.now(timezone.utc).isoformat(),'model':m['model'],'entity_id':str(sample.customer_id),'mode':'shadow','exposed':False,'latency_ms':latency,'raw_prediction':float(pred) if art['task']=='regression' else int(pred)}
        with log.open('a',encoding='utf-8') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
        rows.append({'model':m['model'],'status':'PASS','exposed':False,'latency_ms':round(latency,3)})
    # deterministic A/B distribution across 1000 stable entity ids
    import hashlib
    enabled=sum(int(hashlib.sha256(f'zone-{i}'.encode()).hexdigest()[:8],16)%100<10 for i in range(1000))
    return {'status':'PASS','mode':'shadow','models_loaded':len(models),'shadow_log':str(log),'ab10_sample_entities':1000,'ab10_enabled_entities':enabled,'ab10_fraction':enabled/1000,'models':rows}

def batch_smoke(out_dir,models):
    import joblib
    raw=load_raw(); df=build_features(raw); _,_,te,_=temporal_customer_split(df); total=0; outfiles=[]
    bdir=out_dir/'batch-smoke'; bdir.mkdir(parents=True,exist_ok=True)
    for m in models:
        art=joblib.load(m['artifact']); sample=te.dropna(subset=art['features']).head(100).copy(); pred=art['pipeline'].predict(sample[art['features']]); sample['prediction']=pred; p=bdir/f"{m['model']}_batch100.csv"; sample[['customer_id','observed_at','prediction']].to_csv(p,index=False); total+=len(sample); outfiles.append(str(p))
    return {'status':'PASS','models':len(models),'rows_inferred':total,'files':len(outfiles)}

def monitor(out_dir,deployment):
    records=[]
    p=Path(deployment['shadow_log'])
    for line in p.read_text(encoding='utf-8').splitlines(): records.append(json.loads(line))
    d=pd.DataFrame(records); summary={'records':len(d),'by_model':{}}
    for m,g in d.groupby('model'):
        summary['by_model'][m]={'requests':len(g),'latency_ms_mean':float(g.latency_ms.mean()),'latency_ms_p95':float(g.latency_ms.quantile(.95)),'exposed_fraction':float(g.exposed.mean())}
    save_json(out_dir/'monitoring_summary.json',summary); return summary

def main():
    run_id=utc_run_id(); out=OUTROOT/run_id; out.mkdir(parents=True,exist_ok=True)
    raw=load_raw(); feat=build_features(raw); _,_,_,split=temporal_customer_split(feat); audit=dataset_audit(raw,feat)
    results=[]
    for modname in MODULES:
        print(f'=== TRAIN START {modname} ===',flush=True)
        mod=importlib.import_module(modname); res=mod.run(out); results.append(res); save_json(out/f'{modname}_result.json',res)
        print(f"=== TRAIN DONE {res['model']} | selected={res['selected_algorithm']} | test={res['test_metrics']} ===",flush=True)
    deploy=serving_smoke(out,results); batch=batch_smoke(out,results); mon=monitor(out,deploy)
    full={'version':'10.4-simulation','run_id':run_id,'created_at':datetime.now(timezone.utc).isoformat(),'scope':'SYNTHETIC_SIMULATION_ONLY','production_ready':False,'environment':environment(),'dataset_audit':audit,'split':split,'models':results,'deployment_smoke':deploy,'batch_smoke':batch,'monitoring':mon,'retraining':{'entrypoint':'scripts/retrain_v103.py (production readiness guard) + scripts/model_training_v104/train_all_and_report.py (simulation benchmark)','production_data_guard':'ENABLED','recommended_cycle':'3-6 tháng hoặc theo drift/data readiness','simulation_artifact_auto_promote':'DISABLED'},'training_files':[f'scripts/model_training_v104/{x}.py' for x in MODULES]+['scripts/model_training_v104/common.py','scripts/model_training_v104/report.py','scripts/model_training_v104/train_all_and_report.py']}
    save_json(out/'TRAINING_END_TO_END_REPORT.json',full)
    report=generate(full,out/'BAO_CAO_TRAIN_MODEL_AI_VA_MO_PHONG_HOAN_TAT.docx')
    # materialize latest as a real directory for Windows zip portability
    latest=OUTROOT/'latest'
    if latest.exists(): shutil.rmtree(latest)
    shutil.copytree(out,latest)
    print(json.dumps({'run_id':run_id,'out':str(out),'report':str(report),'models':{m['model']:m['test_metrics'] for m in results},'deployment':deploy,'batch':batch},ensure_ascii=False,indent=2,default=str))
if __name__=='__main__': main()
