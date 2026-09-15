"""Residual forecasts; fixed known-test disclosure, no automatic promotion."""
import argparse,json,sys,platform
from pathlib import Path
from datetime import datetime,timezone
import numpy as np,pandas as pd,joblib,sklearn
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import ExtraTreesRegressor,HistGradientBoostingRegressor
from .historical_training import FEATURES,sha,write_json,metrics
from .contracts import SPECS
from .forecast_acceptance import POLICY,regression_acceptance,classification_acceptance

def run(project,output):
    project=Path(project).resolve();output=Path(output).resolve();out=output/datetime.now(timezone.utc).strftime('residual-%Y%m%dT%H%M%SZ');out.mkdir(parents=True,exist_ok=False)
    pointer=json.loads((project/'model-artifacts/historical-customer/latest_report.json').read_text(encoding='utf-8'))
    source=json.loads(Path(pointer['report_path']).read_text(encoding='utf-8'));fp=Path(source['feature_csv']['path'])
    if sha(fp)!=source['feature_csv']['sha256']:raise ValueError('Sealed feature CSV checksum mismatch')
    frame=pd.read_csv(fp);write_json(out/'policy_before_fit.json',POLICY)
    report={'created_at':datetime.now(timezone.utc).isoformat(),'run_id':out.name,'source_report':pointer['report_path'],
      'source_feature_csv':str(fp),'source_feature_sha256':sha(fp),'source_cleaning':source['cleaning'],'split':source['split'],
      'policy':POLICY,'models':[],'ready_count':0,'active_registry_modified':False,'seed':20260914,
      'scope':'historical_simulated_customer_development_recheck','test_reused':True,
      'disclosure':'The heldout historical period has been examined before. This improvement experiment is NOT a new blind test; future pilot needs a newly frozen test window.',
      'training_change':'Learn y_future-current_value; add current measurement at prediction time. Input current value must be present; no fabricated prediction from a missing current reading.',
      'environment':{'python':platform.python_version(),'sklearn':sklearn.__version__,'pandas':pd.__version__,'numpy':np.__version__}}
    for spec in SPECS:
        if not spec.metric:continue
        sub=frame.loc[frame.metric_type==spec.metric];parts={k:sub.loc[(sub.split==k)&sub.target.notna()&sub.value.notna()].copy() for k in ['train','validation','test_unseen_customer']}
        tr,va,te=parts.values();entry={'name':spec.name,'title':spec.title,'metric':spec.metric,'status':'BLOCKED','rows':{k:len(p) for k,p in parts.items()},'features':FEATURES}
        if min(len(tr),len(va),len(te))<24:entry['reason']='Insufficient valid current/target pairs';report['models'].append(entry);continue
        estimators={'ridge_residual_a1':make_pipeline(StandardScaler(),Ridge(alpha=1)),
          'ridge_residual_a10':make_pipeline(StandardScaler(),Ridge(alpha=10)),
          'extra_trees_residual':ExtraTreesRegressor(n_estimators=160,max_depth=12,min_samples_leaf=12,n_jobs=2,random_state=20260914),
          'hgb_residual':HistGradientBoostingRegressor(max_iter=120,max_leaf_nodes=7,min_samples_leaf=40,l2_regularization=5,early_stopping=False,random_state=20260914)}
        fitted={};validation={}
        for name,est in estimators.items():
            pipeline=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),est)
            pipeline.fit(tr[FEATURES],tr.target-tr.value);fitted[name]=pipeline
            validation[name]=metrics(va.target,pipeline.predict(va[FEATURES])+va.value)
        selected=min(validation,key=lambda k:validation[k]['mae']);pipeline=fitted[selected];entry.update(status='EXPERIMENTAL',algorithm=selected,validation_candidates=validation,metrics={},acceptance={},baselines={},parameters={k:str(v) for k,v in pipeline.get_params().items()})
        folder=out/spec.name;folder.mkdir()
        for split,p in parts.items():
            prediction=pipeline.predict(p[FEATURES])+p.value.to_numpy();entry['metrics'][split]=metrics(p.target,prediction)
            count=int(((sub.split==split)&sub.target.notna()).sum());entry['acceptance'][split]=regression_acceptance(p.target,prediction,spec.metric,count)
            entry['baselines'][split]={'persistence':metrics(p.target,p.value),'persistence_acceptance':regression_acceptance(p.target,p.value,spec.metric,count)}
            records=p[['customer_id','farm_id','zone_id','device_id','sensor_id','decision_at','label_end','reading_id','target_reading_id','target','value']].copy()
            records['prediction']=prediction;records['absolute_error']=abs(records.target-records.prediction)
            records['within_tolerance']=records.absolute_error<=POLICY['tolerances'][spec.metric]
            records.to_csv(folder/(split+'_predictions.csv'),index=False)
        entry['beats_persistence_mae']=entry['metrics']['test_unseen_customer']['mae']<entry['baselines']['test_unseen_customer']['persistence']['mae']
        entry['deployment_ready']=False
        entry['reason']='Known historical synthetic test; tolerance proposal needs review and future independent pilot validation.'
        path=folder/'model.joblib';joblib.dump({'pipeline':pipeline,'features':FEATURES,'metric':spec.metric,'output_transform':'add_current_value','scope':report['scope'],'status':'EXPERIMENTAL'},path,compress=3)
        probe=te[FEATURES].head(20);delta=float(np.max(abs(pipeline.predict(probe)-joblib.load(path)['pipeline'].predict(probe))))
        assert delta<1e-10;entry.update(artifact_path=str(path),artifact_sha256=sha(path),reload_max_difference=delta)
        write_json(folder/'report.json',entry);report['models'].append(entry)
        print(json.dumps({'model':spec.name,'algorithm':selected,'test':entry['metrics']['test_unseen_customer'],'acceptance':entry['acceptance']['test_unseen_customer'],'beats_baseline':entry['beats_persistence_mae']}),flush=True)
    # Audit the six already trained classifiers against the new proposed metric gates.
    bp=json.loads((project/'model-artifacts/benchmark-retrain/latest_report.json').read_text(encoding='utf-8'))
    benchmark=json.loads(Path(bp['report_path']).read_text(encoding='utf-8'));report['existing_classifier_source_report']=bp['report_path'];report['existing_classifier_acceptance']=[]
    for model in benchmark['models']:
        if model['task']!='classification':continue
        score=model['metrics']['test'];report['existing_classifier_acceptance'].append({'name':model['name'],'scope':'existing_synthetic_benchmark_only','acceptance':classification_acceptance(score['confusion_matrix'],score['f1_macro'],score['recall_risk'])})
    code=out/'source';code.mkdir()
    for name in ['refine_forecasts.py','forecast_acceptance.py','historical_training.py','contracts.py']:(code/name).write_bytes((Path(__file__).parent/name).read_bytes())
    report['code_sha256']={p.name:sha(p) for p in code.iterdir()};write_json(out/'training_report.json',report)
    write_json(output/'latest_report.json',{'report_path':str(out/'training_report.json'),'run_id':out.name})
    return report

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--output',required=True);args=p.parse_args();run(args.project,args.output)
