"""Reproducible experiment on existing customer CSV snapshots, never deployment.

Only independent future sensor observations are labels. AI-created alerts and
unverified seed runs cannot become ground truth for fault classifiers.
"""
import argparse, hashlib, json, platform, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .contracts import SPECS

VERSION='historical_customer_experiment_v1'
SEED=20260913
KEYS=['customer_id','farm_id','zone_id','device_id','sensor_id','metric_type']
BOUNDS={'soil_moisture':(0,100),'temperature':(-40,85),'ec':(0,30),'ph':(0,14),'flow_rate':(0,10000),'air_humidity':(0,100)}
UNITS={'soil_moisture':{'%'},'temperature':{'°C','C','degC'},'ec':{'mS/cm'},'ph':{'pH',''},'flow_rate':{'L/phút','L/min'},'air_humidity':{'%RH','%'}}
NULLS={'','null','none','nan','na','n/a','nat','undefined','unknown'}
FEATURES=['value','lag1','lag3','lag6','mean3','slope3','history_missing','reading_age_minutes']

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def write_json(path,obj):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')

def metrics(y,p):
    return {'mae':float(mean_absolute_error(y,p)),'rmse':float(mean_squared_error(y,p)**.5),'r2':float(r2_score(y,p))}

def select_snapshots(root):
    result=[]
    for folder in sorted(Path(root).iterdir()):
        paths=sorted((folder/'snapshots').glob('runtime_*/snapshot_manifest.json'))
        if paths:result.append(paths[-1])
    if len(result)<3:raise ValueError('Need at least three distinct customer snapshots')
    return result

def clean_snapshot(manifest_path,destination):
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    customer=manifest['customer_id'];raw=manifest_path.parent/'raw'
    audit={'customer_id':customer,'manifest_path':str(manifest_path),'manifest_sha256':sha(manifest_path),
      'snapshot_id':manifest['snapshot_id'],'exported_at':manifest['exported_at'],'files':[],
      'cleaning_version':VERSION,'input_rows':0,'rejected_rows':0,'duplicate_reading_ids':0,
      'reason_counts':Counter(),'missing_input':Counter(),'origins':Counter(),'metrics':Counter(),'units':Counter(),'quality':Counter(),
      'policy':'Fixed units/ranges; missing values stay NaN. Last observation available by each 10-minute boundary. No future fill.'}
    for item in manifest['files']:
        path=raw/(item['name']+'.csv');actual=sha(path)
        if actual!=item['sha256']:raise ValueError(f'Source hash mismatch: {path}')
        audit['files'].append({'path':str(path),'rows':item['row_count'],'sha256':actual,'columns':item['columns']})
    pieces=[];seen=set();lo=None;hi=None
    cols=KEYS+['owner_user_id','reading_id','value','unit','quality','observed_at','received_at','data_origin']
    for chunk in pd.read_csv(raw/'sensor_readings.csv',dtype=str,keep_default_na=False,usecols=cols,chunksize=100000):
        audit['input_rows']+=len(chunk)
        for key in cols:audit['missing_input'][key]+=int(chunk[key].str.strip().str.lower().isin(NULLS).sum())
        for col,name in [('data_origin','origins'),('metric_type','metrics'),('unit','units'),('quality','quality')]:audit[name].update(chunk[col].value_counts().to_dict())
        chunk['observed_at']=pd.to_datetime(chunk.observed_at,utc=True,errors='coerce',format='ISO8601')
        chunk['received_at']=pd.to_datetime(chunk.received_at,utc=True,errors='coerce',format='ISO8601')
        cmin,cmax=chunk.observed_at.min(),chunk.observed_at.max()
        lo=cmin if lo is None or cmin<lo else lo;hi=cmax if hi is None or cmax>hi else hi
        reject=pd.Series(False,index=chunk.index)
        reasons={'wrong_customer':chunk.customer_id!=customer,
          'missing_identity':chunk[KEYS+['owner_user_id','reading_id']].apply(lambda s:s.str.strip().str.lower().isin(NULLS)).any(axis=1),
          'invalid_timestamp':chunk.observed_at.isna()|chunk.received_at.isna(),
          'future_clock':chunk.observed_at>chunk.received_at+pd.Timedelta(seconds=30),
          'unknown_metric':~chunk.metric_type.isin(BOUNDS)}
        duplicate=chunk.reading_id.duplicated()|chunk.reading_id.isin(seen)
        seen.update(chunk.loc[~reasons['missing_identity'],'reading_id'])
        audit['duplicate_reading_ids']+=int(duplicate.sum());reasons['duplicate_reading_id']=duplicate
        for reason,mask in reasons.items():audit['reason_counts'][reason]+=int(mask.sum());reject|=mask
        audit['rejected_rows']+=int(reject.sum());chunk=chunk.loc[~reject].copy()
        value=pd.to_numeric(chunk.value.str.strip().str.replace(',','.',regex=False),errors='coerce')
        valid_range=pd.Series(False,index=chunk.index);valid_unit=valid_range.copy()
        for key,(lower,upper) in BOUNDS.items():
            mask=chunk.metric_type.eq(key);valid_range|=mask&value.between(lower,upper);valid_unit|=mask&chunk.unit.isin(UNITS[key])
        quality=chunk.quality.eq('good')
        for reason,mask in [('invalid_or_missing_numeric',~np.isfinite(value)),('invalid_range',np.isfinite(value)&~valid_range),('invalid_unit',~valid_unit),('untrusted_quality',~quality)]:audit['reason_counts'][reason]+=int(mask.sum())
        chunk['value']=value.where(valid_range&valid_unit&quality)
        chunk['decision_at']=chunk.observed_at.dt.ceil('10min')
        late=chunk.received_at>chunk.decision_at
        audit['reason_counts']['not_available_at_boundary']+=int(late.sum())
        chunk=chunk.loc[~late].sort_values(['observed_at','received_at','reading_id'])
        pieces.append(chunk.drop_duplicates(KEYS+['decision_at'],keep='last'))
    reduced=pd.concat(pieces,ignore_index=True).sort_values(['observed_at','received_at','reading_id']).drop_duplicates(KEYS+['decision_at'],keep='last')
    rows=[]
    for keys,part in reduced.groupby(KEYS,sort=True):
        part=part.set_index('decision_at').sort_index()
        grid=pd.date_range(part.index.min(),part.index.max(),freq='10min',name='decision_at')
        part=part.reindex(grid)
        for key,value in zip(KEYS,keys):part[key]=value
        rows.append(part.reset_index())
    clean=pd.concat(rows,ignore_index=True)
    audit.update({'observed_min':lo,'observed_max':hi,'span_hours':(hi-lo).total_seconds()/3600,
      'boundary_rows_before_grid':len(reduced),'grid_rows':len(clean),'empty_grid_rows':int(clean.reading_id.isna().sum()),
      'missing_value_after':int(clean.value.isna().sum()),'series_count':len(rows),
      'retained_rows_note':'Reduction is causal 10-minute sampling, not arbitrary row deletion; original raw CSV preserved.'})
    destination.mkdir(parents=True,exist_ok=True);path=destination/'sensor_readings_10min.csv'
    clean.to_csv(path,index=False);audit['cleaned_csv']={'path':str(path),'sha256':sha(path),'rows':len(clean)}
    write_json(destination/'cleaning_report.json',audit)
    print(json.dumps({'cleaned_customer':customer,'raw_rows':audit['input_rows'],'span_hours':audit['span_hours'],'grid_rows':len(clean)},ensure_ascii=False),flush=True)
    return clean,audit

def features(clean):
    frames=[]
    for keys,part in clean.groupby(KEYS,sort=True):
        part=part.sort_values('decision_at').copy()
        for k in (1,3,6):part[f'lag{k}']=part.value.shift(k)
        part['mean3']=part.value.rolling(3,min_periods=1).mean()
        part['slope3']=(part.value-part.lag3)/30
        part['history_missing']=part.value.isna().rolling(7,min_periods=1).sum()
        part['reading_age_minutes']=(part.decision_at-part.observed_at).dt.total_seconds()/60
        part['label_end']=part.decision_at+pd.Timedelta(minutes=30)
        part['target_observed_at']=part.observed_at.shift(-3)
        part['target_reading_id']=part.reading_id.shift(-3)
        exact=(part.target_observed_at-part.label_end).abs()<=pd.Timedelta(seconds=60)
        part['target']=part.value.shift(-3).where(exact & (part.target_observed_at>part.decision_at))
        frames.append(part)
    return pd.concat(frames,ignore_index=True)

def split_frame(frame,heldout):
    ranges=frame.groupby(KEYS).decision_at.agg(['min','max'])
    start=ranges['min'].max();end=ranges['max'].min();span=end-start
    if span<pd.Timedelta(hours=24):raise ValueError('Less than 24h common archive coverage; cannot split reliably')
    cut1=(start+span*.60).floor('10min');cut2=(start+span*.80).floor('10min')
    frame=frame.copy();frame['split']='excluded'
    dev=frame.customer_id!=heldout
    frame.loc[dev&(frame.decision_at>=start)&(frame.label_end<cut1),'split']='train'
    frame.loc[dev&(frame.decision_at>=cut1)&(frame.label_end<cut2),'split']='validation'
    frame.loc[(frame.decision_at>=cut2)&(frame.label_end<=end)&dev,'split']='test_seen_customers'
    frame.loc[(frame.decision_at>=cut2)&(frame.label_end<=end)&~dev,'split']='test_unseen_customer'
    return frame,{'start':start,'end':end,'common_span_hours':span.total_seconds()/3600,'train_end':cut1,'validation_end':cut2,
      'heldout_customer':heldout,'time_ratio':'60/20/20 with strict 30-minute label purge',
      'policy':'Heldout customer excluded entirely from training/validation. Heldout earlier period excluded. No test selection or final refit.'}

def fit_models(frame,out,report):
    for spec in SPECS:
        record={'name':spec.name,'title':spec.title,'task':spec.task,'target':spec.target,'status':'BLOCKED','source':'customer_exports',
          'scope':'historical_simulated_customer_experiment','horizon_minutes':spec.horizon_minutes}
        if spec.task!='regression':
            record['reason']='No independent incident timeline in these three customer snapshots. AI-generated alerts and demo_seed_v10 runs excluded as labels.'
            record['required_label']=spec.target.removesuffix('_future')+' with confirmed onset/end, customer/device IDs and observation coverage'
            report['models'].append(record);continue
        part=frame.loc[frame.metric_type==spec.metric].copy()
        parts={key:part.loc[(part.split==key)&part.target.notna()].copy() for key in ['train','validation','test_seen_customers','test_unseen_customer']}
        record['rows']={key:len(p) for key,p in parts.items()}
        record['missing_targets_excluded']=int(part.target.isna().sum())
        if any(len(parts[k])<minimum for k,minimum in [('train',100),('validation',24),('test_unseen_customer',24)]):
            record['reason']='Too few valid aligned future observations';report['models'].append(record);continue
        dest=out/spec.name;dest.mkdir(parents=True,exist_ok=True)
        train,val=parts['train'],parts['validation'];candidates={
          'Ridge':make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),StandardScaler(),Ridge(alpha=10)),
          'HistGradientBoosting':make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),HistGradientBoostingRegressor(max_iter=150,max_leaf_nodes=15,min_samples_leaf=30,l2_regularization=3,early_stopping=False,random_state=SEED)),
          'ExtraTrees':make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),ExtraTreesRegressor(n_estimators=160,max_depth=12,min_samples_leaf=8,n_jobs=2,random_state=SEED))}
        validation={}
        for name,model in candidates.items():
            model.fit(train[FEATURES],train.target);validation[name]=metrics(val.target,model.predict(val[FEATURES]))
        chosen=min(validation,key=lambda name:validation[name]['mae']);model=candidates[chosen]
        record.update({'status':'EXPERIMENTAL','algorithm':chosen,'validation_candidates':validation,'features':FEATURES,
          'parameters':{k:str(v) for k,v in model.get_params().items()},'test_metrics':{},'baselines':{},'per_customer':{},
          'reason':'Measured on historical simulated exports; not field validation and not automatically activated.'})
        for name,p in parts.items():
            if not len(p):continue
            pred=model.predict(p[FEATURES]);record['test_metrics'][name]=metrics(p.target,pred)
            med=train.value.median()
            if not np.isfinite(med):raise ValueError('No training values for baseline')
            now=p.value.fillna(med).to_numpy();lag=p.lag3.fillna(med).to_numpy()
            baseline={'persistence':now,'moving_average':p.mean3.fillna(med).to_numpy(),'linear_trend':now+(now-lag)}
            record['baselines'][name]={k:metrics(p.target,v) for k,v in baseline.items()}
            result=p[KEYS+['decision_at','label_end','reading_id','target_reading_id','target_observed_at','target']].copy()
            result['prediction']=pred;result['absolute_error']=abs(pred-p.target.to_numpy())
            for k,v in baseline.items():result[k]=v
            result.to_csv(dest/(name+'_predictions.csv'),index=False)
            record['per_customer'][name]={str(c):metrics(g.target,g.prediction) for c,g in result.groupby('customer_id')}
            if name.startswith('test'):result.nlargest(20,'absolute_error').to_csv(dest/(name+'_largest_errors.csv'),index=False)
        baseline_choice=min(record['baselines']['validation'],key=lambda k:record['baselines']['validation'][k]['mae'])
        mae=record['test_metrics']['test_unseen_customer']['mae'];bmae=record['baselines']['test_unseen_customer'][baseline_choice]['mae']
        record['validation_selected_baseline']=baseline_choice
        record['mae_gain_vs_validation_selected_baseline']=None if bmae==0 else (bmae-mae)/bmae
        record['better_than_baseline_on_unseen_customer']=mae<bmae
        record['artifact_path']=str(dest/'model.joblib')
        joblib.dump({'model':model,'features':FEATURES,'spec':spec,'scope':record['scope'],'status':'EXPERIMENTAL',
          'training_version':VERSION,'sklearn_version':sklearn.__version__},record['artifact_path'],compress=3)
        reloaded=joblib.load(record['artifact_path']);probe=parts['test_unseen_customer'][FEATURES].head(30)
        record['artifact_reload_max_difference']=float(np.max(abs(model.predict(probe)-reloaded['model'].predict(probe))))
        record['artifact_reload_tolerance']={'rtol':1e-12,'atol':1e-12}
        assert np.allclose(model.predict(probe),reloaded['model'].predict(probe),rtol=1e-12,atol=1e-12)
        record['artifact_sha256']=sha(record['artifact_path'])
        # Trace every model back to the exact cleaned source and split features.
        record['data_files']=[a['cleaned_csv'] for a in report['cleaning']]
        record['feature_csv']=report['feature_csv']
        write_json(dest/'report.json',record);report['models'].append(record)
        print(json.dumps({'trained':spec.name,'selected':chosen,'test':record['test_metrics']['test_unseen_customer'],'baseline':baseline_choice},ensure_ascii=False),flush=True)

def run(project):
    project=Path(project).resolve();run_id=datetime.now(timezone.utc).strftime('historical-%Y%m%dT%H%M%SZ')
    data=project/'model-artifacts/data/historical-customer'/run_id
    artifacts=project/'model-artifacts/historical-customer'/run_id
    data.mkdir(parents=True,exist_ok=False);artifacts.mkdir(parents=True,exist_ok=False)
    manifests=select_snapshots(project/'model-artifacts/data/customers')
    report={'run_id':run_id,'created_at':datetime.now(timezone.utc).isoformat(),'training_version':VERSION,'seed':SEED,
      'scope':'Existing simulated customer exports, separate from current 72h runtime collection and from synthetic 42-day benchmark',
      'python':platform.python_version(),'libraries':{'numpy':np.__version__,'pandas':pd.__version__,'sklearn':sklearn.__version__,'joblib':joblib.__version__},
      'cleaning':[],'models':[],'active_registry_modified':False,'ready_models':0,
      'limits':['Historical source timestamps do not satisfy a new runtime 72h collection contract.',
        'These archives may have appeared in earlier project experiments; this is a reproducible new split, not a claim of a never-seen external benchmark.',
        'Only one customer is held out, with less than a season of observation; no population or seasonal accuracy claim.']}
    frames=[]
    for manifest in manifests:
        clean,audit=clean_snapshot(manifest,data/json.loads(manifest.read_text(encoding='utf-8'))['customer_id'])
        frames.append(clean);report['cleaning'].append(audit)
    clean=pd.concat(frames,ignore_index=True);heldout=sorted(clean.customer_id.unique())[-1]
    frame,split=split_frame(features(clean),heldout);report['split']=split
    feature_path=data/'features_with_split.csv';frame.to_csv(feature_path,index=False)
    report['feature_csv']={'path':str(feature_path),'sha256':sha(feature_path),'rows':len(frame)}
    frame.groupby(['customer_id','metric_type','split']).agg(rows=('value','size'),valid_values=('value','count'),valid_targets=('target','count')).reset_index().to_csv(data/'split_counts.csv',index=False)
    write_json(data/'dataset_manifest.json',{k:v for k,v in report.items() if k!='models'})
    write_json(artifacts/'training_started.json',report)
    fit_models(frame,artifacts,report)
    # Preserve source code beside artifacts for audit/reproduction.
    code=artifacts/'source';code.mkdir()
    for filename in ['historical_training.py','contracts.py']:
        (code/filename).write_bytes((Path(__file__).parent/filename).read_bytes())
    report['code_sha256']={p.name:sha(p) for p in code.iterdir()}
    write_json(artifacts/'training_report.json',report)
    pd.DataFrame([{'model':m['name'],'status':m['status'],'algorithm':m.get('algorithm'),**m.get('test_metrics',{}).get('test_unseen_customer',{}),'reason':m['reason']} for m in report['models']]).to_csv(artifacts/'model_summary.csv',index=False,encoding='utf-8-sig')
    write_json(project/'model-artifacts/historical-customer/latest_report.json',{'report_path':str(artifacts/'training_report.json'),'run_id':run_id})
    print('REPORT '+str(artifacts/'training_report.json'),flush=True)
    return report

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser();parser.add_argument('--project',required=True)
    run(parser.parse_args().project)
