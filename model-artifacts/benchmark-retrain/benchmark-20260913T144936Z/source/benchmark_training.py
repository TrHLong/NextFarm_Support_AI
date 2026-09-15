"""Retrain ten models on an existing labeled simulator benchmark, no promotion."""
import argparse,json,sys,platform
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
import joblib,sklearn
from sklearn.ensemble import HistGradientBoostingClassifier,HistGradientBoostingRegressor,ExtraTreesRegressor
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.feature_selection import VarianceThreshold
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from .contracts import SPECS
from .data_quality import normalize_values,missing_counts,expected_fields,CLEANING_VERSION
from .historical_training import sha,write_json
from .ml import prepare_features,scores,baselines,coverage,FORBIDDEN

SEED=20260913

def clean_existing(source,destination):
    original=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    if original['source']!='synthetic_device_spec_v11':raise ValueError('Expected explicitly synthetic source')
    audit=[];files=[]
    for record in original['files']:
        rel=Path(record['path'].replace('\\','/'));path=(source/rel).resolve()
        if not path.is_relative_to(source.resolve()) or sha(path)!=record['sha256']:raise ValueError('Invalid source/hash: '+str(path))
        raw=pd.read_csv(path,keep_default_na=False,dtype=str);group=path.stem
        before=raw.to_dict('records');rows=[];changes=[];rejected=[];seen=set()
        for index,row in enumerate(before):
            if not row.get('customer_id') or not row.get('device_id'):rejected.append(index);continue
            if 'observed_at' in row:
                at=pd.to_datetime(row['observed_at'],utc=True,errors='coerce')
                if pd.isna(at):rejected.append(index);continue
                key=(row['customer_id'],row['device_id'],at)
                if key in seen:rejected.append(index);continue
                seen.add(key);row={**row,'observed_at':at.isoformat()}
            fixed,edits=normalize_values(row,group)
            changes.extend({'row':index,**edit} for edit in edits);rows.append(fixed)
        fields=list(dict.fromkeys(list(raw.columns)+expected_fields(group)))
        cleaned=pd.DataFrame(rows,columns=list(dict.fromkeys(list(raw.columns)+[k for r in rows for k in r])))
        dest=destination/rel;dest.parent.mkdir(parents=True,exist_ok=True);cleaned.to_csv(dest,index=False)
        files.append({'path':str(rel),'rows':len(cleaned),'sha256':sha(dest)})
        # Numeric strings are normal CSV parsing, not data corruption. Summarize edits.
        from collections import Counter
        reasons=Counter(edit.get('reason','normalization') for edit in changes)
        audit.append({'file':str(rel),'raw_path':str(path),'raw_sha256':record['sha256'],'input_rows':len(raw),'cleaned_rows':len(cleaned),
          'rejected_row_indices':rejected,'change_counts':dict(reasons),'change_examples':changes[:20],
          'missing_before':missing_counts(before,fields),'missing_after':missing_counts(rows,fields)})
        print('CLEAN '+str(rel),flush=True)
    manifest={**original,'files':files,'original_source_manifest':str(source/'manifest.json'),
      'original_manifest_sha256':sha(source/'manifest.json'),'cleaning_version':CLEANING_VERSION,
      'generated_new_data':False,'created_at':datetime.now(timezone.utc).isoformat()}
    write_json(destination/'manifest.json',manifest);write_json(destination/'cleaning_report.json',audit)
    return manifest

def make_frame(root):
    result=[]
    for folder in sorted((root/'customers').iterdir()):
        sensor=pd.read_csv(folder/'sensor_readings.csv');status=pd.read_csv(folder/'device_status.csv')
        truth=pd.read_csv(folder/'incident_ground_truth.csv')
        for df in [sensor,status,truth]:df['observed_at']=pd.to_datetime(df.observed_at,utc=True,format='ISO8601')
        frame,columns=prepare_features(sensor,status)
        origin=sensor.set_index('observed_at').sort_index();truth=truth.set_index('observed_at').sort_index()
        grid=pd.date_range(truth.index.min(),truth.index.max(),freq='10min');truth=truth.reindex(grid)
        for spec in SPECS:
            if spec.metric:
                target=origin[spec.metric].where(~origin.quality.isin(['bad','suspect']))
                # These offline timestamps are exact 10-minute simulator samples.
                frame[spec.target]=target.reindex(pd.DatetimeIndex(frame.observed_at+pd.Timedelta(minutes=30))).to_numpy()
            else:
                key=spec.target.removesuffix('_future')
                state=pd.to_numeric(truth[key],errors='coerce').where(truth.ground_truth_origin.eq('synthetic_latent_incident'))
                state=state.where(state.isin([0,1]))
                future=pd.concat([state.shift(-i) for i in range(1,7)],axis=1)
                label=future.max(axis=1).where(state.eq(0)&future.notna().all(axis=1))
                frame[spec.target]=label.reindex(pd.DatetimeIndex(frame.observed_at)).to_numpy()
        frame['label_end']=frame.observed_at+pd.Timedelta(minutes=60);result.append(frame)
    return pd.concat(result,ignore_index=True),columns

def episodes(part,target):
    total=0
    for _,g in part.groupby('device_id'):
        g=g.sort_values('observed_at');labels=g[target]
        total+=int(((labels==1)&((labels.shift(1,fill_value=0)!=1)|(g.observed_at.diff()>pd.Timedelta(minutes=20)))).sum())
    return total

def run(project,source):
    project=Path(project).resolve();source=Path(source).resolve();run_id=datetime.now(timezone.utc).strftime('benchmark-%Y%m%dT%H%M%SZ')
    data=project/'model-artifacts/data/benchmark-retrain'/run_id
    out=project/'model-artifacts/benchmark-retrain'/run_id
    data.mkdir(parents=True,exist_ok=False);out.mkdir(parents=True,exist_ok=False)
    manifest=clean_existing(source,data);frame,columns=make_frame(data)
    customers=sorted(frame.customer_id.unique());heldout=customers[-3:];dev=customers[:-3]
    if len(dev)<6:raise ValueError('Need at least 6 development and 3 heldout synthetic customers')
    start=frame.observed_at.min();end=frame.observed_at.max();duration=end-start
    cut1=(start+duration*.70).floor('10min');cut2=(start+duration*.85).floor('10min')
    frame['split']='excluded';development=frame.customer_id.isin(dev)
    frame.loc[development&(frame.label_end<cut1),'split']='train'
    frame.loc[development&(frame.observed_at>=cut1)&(frame.label_end<cut2),'split']='validation'
    frame.loc[~development&(frame.observed_at>=cut2)&(frame.label_end<=end),'split']='test'
    feature_path=data/'features_with_split.csv';frame.to_csv(feature_path,index=False)
    report={'run_id':run_id,'created_at':datetime.now(timezone.utc).isoformat(),'scope':'existing_synthetic_benchmark_only',
      'source_manifest':str(source/'manifest.json'),'cleaned_manifest':str(data/'manifest.json'),'cleaning_report':str(data/'cleaning_report.json'),
      'feature_csv':str(feature_path),'feature_sha256':sha(feature_path),'ready_count':0,'active_registry_modified':False,
      'train_customers':dev,'held_out_customers':heldout,'seed':SEED,'models':[],
      'split':{'start':start,'end':end,'train_end':cut1,'validation_end':cut2,'policy':'70/15/15 chronological, hold out 3 entire customers, 60min purge, validation selection only; no refit'},
      'environment':{'python':platform.python_version(),'sklearn':sklearn.__version__,'pandas':pd.__version__,'numpy':np.__version__,'joblib':joblib.__version__},
      'limits':['All 12 customers and incident labels are simulated, not field observations.',
        'This existing dataset was used in previous experiments. Current results are a reproducible re-evaluation, not an untouched external test.',
        'Fault precursor strength and frequency are simulator assumptions; a model may learn the generator.',
        'No production accuracy or READY status follows from these results. No current customer CSV is mixed into this benchmark.']}
    for index,spec in enumerate(SPECS):
        print('TRAIN '+spec.name,flush=True)
        cols=[c for c in columns if c==spec.metric or c.startswith(spec.metric+'_') or c=='history_gap_minutes'] if spec.metric else [c for c in columns if not c.startswith(('soil_moisture','temperature','ec','ph','air_humidity'))]
        assert not set(cols)&FORBIDDEN
        parts={split:frame.loc[frame.split==split].dropna(subset=[spec.target]+([spec.metric] if spec.metric else [])).copy() for split in ['train','validation','test']}
        tr,va,te=parts.values();entry={'name':spec.name,'title':spec.title,'task':spec.task,'features':cols,'target':spec.target,
          'horizon_minutes':spec.horizon_minutes,'status':'BLOCKED','rows':{k:len(v) for k,v in parts.items()},'gate_reasons':[]}
        if min(map(len,parts.values()))<100:entry['gate_reasons'].append('Fewer than 100 valid rows per partition')
        if not spec.metric:
            entry['class_coverage']={};entry['positive_episodes']={}
            groups=[('train',tr,50,5),('validation',va,10,2)]+[(str(c),p,5,2) for c,p in te.groupby('customer_id')]
            for name,p,minimum,episode_min in groups:
                counts,ok=coverage(p,spec.target,minimum);entry['class_coverage'][name]=counts
                entry['positive_episodes'][name]=episodes(p,spec.target)
                if not ok or entry['positive_episodes'][name]<episode_min:entry['gate_reasons'].append('Insufficient class/episode coverage '+name)
        if entry['gate_reasons']:report['models'].append(entry);continue
        candidates={'HGB':HistGradientBoostingRegressor(max_iter=120,max_leaf_nodes=15,l2_regularization=2,early_stopping=False,random_state=SEED)} if spec.metric else {
          'HGB':HistGradientBoostingClassifier(max_iter=120,max_leaf_nodes=7,l2_regularization=2,early_stopping=False,random_state=SEED),
          'HGB_detailed':HistGradientBoostingClassifier(max_iter=180,max_leaf_nodes=15,l2_regularization=2,early_stopping=False,random_state=SEED),
          'HGB_balanced':HistGradientBoostingClassifier(max_iter=180,max_leaf_nodes=15,l2_regularization=2,class_weight='balanced',early_stopping=False,random_state=SEED)}
        if spec.metric:candidates.update(Ridge=make_pipeline(StandardScaler(),Ridge(alpha=10)),ExtraTrees=ExtraTreesRegressor(n_estimators=100,min_samples_leaf=5,max_features=.8,max_depth=16,n_jobs=2,random_state=SEED))
        validation={};fitted={};offset_tr=tr[spec.metric].to_numpy() if spec.metric else 0;offset_va=va[spec.metric].to_numpy() if spec.metric else 0
        for name,est in candidates.items():
            pipe=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),VarianceThreshold(),est)
            pipe.fit(tr[cols],tr[spec.target]-offset_tr);fitted[name]=pipe
            validation[name]=scores(va[spec.target],pipe.predict(va[cols])+offset_va,spec.task)
        selected=min(validation,key=lambda k:validation[k]['mae']) if spec.metric else max(validation,key=lambda k:validation[k]['f1_macro'])
        pipe=fitted[selected];entry.update(status='EXPERIMENTAL',algorithm=selected,validation_candidates=validation,
          parameters={k:str(v) for k,v in pipe.get_params().items()},metrics={},baselines={},per_customer={})
        for split,p in parts.items():
            offset=p[spec.metric].to_numpy() if spec.metric else 0;pred=pipe.predict(p[cols])+offset
            base=baselines(spec,p,tr);entry['metrics'][split]=scores(p[spec.target],pred,spec.task)
            entry['baselines'][split]={k:scores(p[spec.target],v,spec.task) for k,v in base.items()}
            predictions=p[['customer_id','device_id','observed_at','label_end',spec.target]].copy();predictions['prediction']=pred
            for key,v in base.items():predictions[key]=v
            if not spec.metric:predictions['probability_uncalibrated']=pipe.predict_proba(p[cols])[:,1]
            predictions.to_csv(out/(spec.name+'_'+split+'_predictions.csv'),index=False)
            entry['per_customer'][split]={str(c):scores(g[spec.target],g.prediction,spec.task) for c,g in predictions.groupby('customer_id')}
            if split=='test':
                predictions['absolute_error']=abs(predictions.prediction-predictions[spec.target])
                predictions.nlargest(20,'absolute_error').to_csv(out/(spec.name+'_largest_errors.csv'),index=False)
        metric='mae' if spec.metric else 'f1_macro';valbase=entry['baselines']['validation']
        best=min(valbase,key=lambda k:valbase[k][metric]) if spec.metric else max(valbase,key=lambda k:valbase[k][metric])
        entry['validation_selected_baseline']=best;testscore=entry['metrics']['test'][metric];base=entry['baselines']['test'][best][metric]
        entry['baseline_gain']=(base-testscore)/base if spec.metric and base>0 else testscore-base if not spec.metric else 0
        entry['benchmark_passed']=bool(entry['baseline_gain']>=.03 if spec.metric else entry['baseline_gain']>=.02 and testscore>=.65 and entry['metrics']['test']['recall_risk']>=.5)
        entry['macro_across_test_customers']=float(np.mean([m[metric] for m in entry['per_customer']['test'].values()]))
        entry['gate_reasons']=['Synthetic experiment; no field acceptance']+([] if entry['benchmark_passed'] else ['Baseline/recall gate failed'])
        path=out/(spec.name+'.joblib');joblib.dump({'pipeline':pipe,'features':cols,'metric':spec.metric,'scope':report['scope'],'status':'EXPERIMENTAL','sklearn_version':sklearn.__version__},path,compress=3)
        probe=te[cols].head(100);difference=float(np.max(abs(pipe.predict(probe)-joblib.load(path)['pipeline'].predict(probe))))
        assert np.allclose(pipe.predict(probe),joblib.load(path)['pipeline'].predict(probe),rtol=1e-12,atol=1e-12)
        entry.update(artifact_path=str(path),artifact_sha256=sha(path),reload_max_difference=difference,reload_tolerance={'rtol':1e-12,'atol':1e-12},
          source_csvs=[str(data/f['path']) for f in manifest['files'] if Path(f['path']).stem in ['sensor_readings','device_status','incident_ground_truth']],
          feature_csv=str(feature_path),cleaning_report=report['cleaning_report'])
        write_json(out/(spec.name+'_report.json'),entry);report['models'].append(entry)
        print(json.dumps({'trained':spec.name,'algorithm':selected,'test':entry['metrics']['test'],'status':entry['status']}),flush=True)
    code=out/'source';code.mkdir()
    for name in ['benchmark_training.py','historical_training.py','data_quality.py','ml.py','contracts.py']:(code/name).write_bytes((Path(__file__).parent/name).read_bytes())
    report['code_sha256']={p.name:sha(p) for p in code.iterdir()}
    write_json(out/'training_report.json',report)
    pd.DataFrame([{'model':m['name'],'status':m['status'],'algorithm':m.get('algorithm'),**m.get('metrics',{}).get('test',{})} for m in report['models']]).to_csv(out/'model_summary.csv',index=False,encoding='utf-8-sig')
    write_json(project/'model-artifacts/benchmark-retrain/latest_report.json',{'run_id':run_id,'report_path':str(out/'training_report.json')})
    print('REPORT '+str(out/'training_report.json'),flush=True)
    return report

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser();parser.add_argument('--project',required=True);parser.add_argument('--source',required=True)
    args=parser.parse_args();run(args.project,args.source)
