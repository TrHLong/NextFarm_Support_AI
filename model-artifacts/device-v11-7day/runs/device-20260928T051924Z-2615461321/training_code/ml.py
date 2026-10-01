"""Auditable device ML. Frozen test sites, purged time split, train-only transforms.
No user IDs, profile categories, fault scenarios or contemporaneous weak labels
are model inputs. Report contains explicit baselines and deployment scope.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.feature_selection import VarianceThreshold
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, accuracy_score, f1_score, recall_score, confusion_matrix
from .contracts import SPECS

SIGNALS=['soil_moisture','temperature','ec','ph','air_humidity','flow_rate',
 'pressure','pump_current','sensor_bus_errors','supply_voltage','rssi','packet_loss_rate','command_failure_rate']
FORBIDDEN={'customer_id','device_id','ground_truth_origin','profile_type','scenario','power_state','mqtt_state','online'}

def prepare_features(sensor,status):
    sensor=sensor.copy();status=status.copy()
    for df in (sensor,status):
        df['observed_at']=pd.to_datetime(df['observed_at'],utc=True,format='ISO8601')
        df.sort_values('observed_at',inplace=True)
        df.drop_duplicates('observed_at',keep='last',inplace=True)
    status=status.drop(columns=[x for x in status if x in sensor and x!='observed_at'])
    frame=pd.merge_asof(sensor,status,on='observed_at',direction='backward',tolerance=pd.Timedelta(seconds=30))
    features=[]
    for key in SIGNALS:
        if key not in frame: frame[key]=np.nan
        frame[key]=pd.to_numeric(frame[key],errors='coerce')
        if key in ['soil_moisture','temperature','ec','ph','air_humidity','flow_rate'] and 'quality' in frame:
            frame.loc[frame.quality.isin(['bad','suspect']),key]=np.nan
        features.append(key)
        for lag in [1,3,6]:
            col=f'{key}_lag{lag}';frame[col]=frame[key].shift(lag);features.append(col)
        col=f'{key}_missing';frame[col]=frame[key].isna().astype(float);features.append(col)
        col=f'{key}_mean3';frame[col]=frame[key].rolling(3,min_periods=1).mean();features.append(col)
        minutes=(frame.observed_at-frame.observed_at.shift(3)).dt.total_seconds()/60
        col=f'{key}_slope3';frame[col]=(frame[key]-frame[key].shift(3))/minutes.replace(0,np.nan);features.append(col)
    frame['history_gap_minutes']=frame.observed_at.diff().dt.total_seconds()/60
    features.append('history_gap_minutes')
    # Unknown state stays NaN; imputer learned solely on train, with missing indicators.
    for key in ['pump_running','valve_running','fertilizer_running']:
        if key not in frame:frame[key]=np.nan
        frame[key]=pd.to_numeric(frame[key],errors='coerce');features.append(key)
    return frame,features

def build_frame(data_root):
    frames=[];sources=[]
    for folder in sorted((Path(data_root)/'customers').iterdir()):
        sensor=pd.read_csv(folder/'sensor_readings.csv');status=pd.read_csv(folder/'device_status.csv')
        truth=pd.read_csv(folder/'incident_ground_truth.csv');truth.observed_at=pd.to_datetime(truth.observed_at,utc=True)
        df,features=prepare_features(sensor,status)
        lookup=sensor.assign(observed_at=pd.to_datetime(sensor.observed_at,utc=True)).set_index('observed_at')
        for spec in SPECS:
            if spec.task=='regression':
                values=lookup[spec.metric].copy()
                if 'quality' in lookup:values.loc[lookup.quality.isin(['bad','suspect'])]=np.nan
                future=pd.merge_asof(pd.DataFrame({'target_at':df.observed_at+pd.Timedelta(minutes=30)}),values.rename('target_value').reset_index().rename(columns={'observed_at':'target_at'}),on='target_at',direction='nearest',tolerance=pd.Timedelta(seconds=60))
                df[spec.target]=future.target_value.to_numpy()
            else:
                key=spec.target.removesuffix('_future')
                series=truth.set_index('observed_at')[key]
                onsets=((series==1)&(series.shift(1,fill_value=0)==0)).astype(int)
                event_times=series.index[onsets==1].asi8
                observed=df.observed_at.astype('int64').to_numpy();horizon=60*60*1_000_000_000
                future=(np.searchsorted(event_times,observed+horizon,side='right')>np.searchsorted(event_times,observed,side='right')).astype(float)
                current=pd.merge_asof(df[['observed_at']],series.rename('current_incident').reset_index(),on='observed_at',direction='backward',tolerance=pd.Timedelta(minutes=11))
                future[(current.current_incident.to_numpy()!=0)|(observed+horizon>series.index.max().value)]=np.nan
                df[spec.target]=future
        df['label_end']=df.observed_at+pd.Timedelta(minutes=60)
        frames.append(df);sources.append(str(folder/'sensor_readings.csv'))
    return pd.concat(frames,ignore_index=True),features,sources

def scores(y,p,task):
    if task=='regression':return {'mae':float(mean_absolute_error(y,p)),'rmse':float(mean_squared_error(y,p)**.5),'r2':float(r2_score(y,p))}
    return {'accuracy':float(accuracy_score(y,p)),'f1_macro':float(f1_score(y,p,average='macro',labels=[0,1],zero_division=0)),
       'recall_risk':float(recall_score(y,p,labels=[1],average='macro',zero_division=0)),
       'confusion_matrix':confusion_matrix(y,p,labels=[0,1]).tolist()}

def baselines(spec,part,train):
    if spec.task=='regression':
        now=part[spec.metric].ffill().fillna(train[spec.metric].median()).to_numpy()
        lag=part[f'{spec.metric}_lag3'].fillna(train[spec.metric].median()).to_numpy()
        return {'persistence':now,'moving_average':part[f'{spec.metric}_mean3'].fillna(train[spec.metric].median()).to_numpy(),
                'linear_trend':now+(now-lag)}
    rules={'no_flow_future':('pressure',1.5,'lt'),'leak_future':('pressure',2.3,'lt'),
      'irrigation_abort_future':('pump_current',6,'gt'),'sensor_fault_future':('sensor_bus_errors',20,'gt'),
      'power_loss_future':('supply_voltage',20,'lt'),'mqtt_loss_future':('packet_loss_rate',.5,'gt')}
    key,value,op=rules[spec.target];col=part[key]
    rule=(col<value if op=='lt' else col>value).fillna(False).astype(int).to_numpy()
    return {'majority':np.repeat(int(train[spec.target].mode().iloc[0]),len(part)),'current_threshold_rule':rule}

def coverage(df,target,minimum):
    counts={str(i):int((df[target]==i).sum()) for i in [0,1]}
    return counts,all(v>=minimum for v in counts.values())

def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8');os.replace(tmp,path)

def publish_registry(root,report,active):
    """A failed new suite cannot erase the previously accepted deployment."""
    root=Path(root);old=root/'active_models.json'
    previous=json.loads(old.read_text(encoding='utf-8')) if old.exists() else {'models':{}}
    promoted=len(active)==len(SPECS)
    report['deployment']={'promoted':promoted,'policy':'All 10 model gates must pass before automatic replacement',
       'active_model_count':len(active) if promoted else len(previous.get('models',{})),
       'active_dataset_version':report['dataset_version'] if promoted else previous.get('dataset_version')}
    write_json(root/'latest_candidate_report.json',report)
    if promoted:
        write_json(root/'latest_training_report.json',report)
        write_json(old,{'dataset_version':report['dataset_version'],'scope':'simulation_only','production_ready':False,'models':active})
    return report['deployment']

def train_suite(data_root,artifact_root):
    root=Path(artifact_root);data_root=Path(data_root)
    manifest=json.loads((data_root/'manifest.json').read_text(encoding='utf-8'))
    for source in manifest['files']:
        if hashlib.sha256((data_root/source['path']).read_bytes()).hexdigest()!=source['sha256']:raise ValueError('CSV checksum mismatch: '+source['path'])
    frame,features,sources=build_frame(data_root)
    sites=sorted(frame.customer_id.unique());holdout=sites[-3:];development=sites[:-3]
    if len(sites)<9:raise ValueError('Need >=9 independent synthetic sites for this experiment contract')
    times=sorted(frame.observed_at.unique());boundary=pd.Timestamp(times[int(len(times)*.70)])
    test_boundary=pd.Timestamp(times[int(len(times)*.85)])
    train_mask=frame.customer_id.isin(development)&(frame.label_end<boundary)
    val_mask=frame.customer_id.isin(development)&(frame.observed_at>=boundary)&(frame.label_end<test_boundary)
    test_mask=frame.customer_id.isin(holdout)&(frame.observed_at>=test_boundary)
    frame['split']='excluded_or_purged';frame.loc[train_mask,'split']='train';frame.loc[val_mask,'split']='validation';frame.loc[test_mask,'split']='test_unseen_customer'
    run='device-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+hashlib.sha256((data_root/'manifest.json').read_bytes()).hexdigest()[:10]
    out=root/'runs'/run;out.mkdir(parents=True,exist_ok=True)
    import shutil
    code_dir=out/'training_code';code_dir.mkdir()
    for source in ['ml.py','simulation.py','contracts.py']:shutil.copy2(Path(__file__).parent/source,code_dir/source)
    frame.to_csv(out/'processed_features_targets.csv',index=False)
    report={'dataset_version':run,'created_at':datetime.now(timezone.utc).isoformat(),'source_manifest':str(data_root/'manifest.json'),
      'origin':manifest['source'],'scope':'simulation_only','production_ready':False,'field_validation':False,
      'synthetic_customers':len(sites),'real_customers':0,'raw_files':manifest['files'],'processed_rows':len(frame),
      'unique_timestamps':int(frame.observed_at.nunique()),'duration_days':manifest['days'],
      'split_counts':frame.split.value_counts().to_dict(),'training_customers':development,'held_out_customers':holdout,
      'train_label_end_before':boundary.isoformat(),'validation_label_end_before':test_boundary.isoformat(),
      'split_policy':'Chronological development train 70%, validation 15%; final 15% of 3 completely unseen customers. Purge 60 min.',
      'candidate_selection':'validation only; no refit/calibration after selection; exact evaluated artifact is exported',
      'cleaning':'UTC ISO8601 parse, sorted timestamps, duplicate removal, numeric coercion; bad/suspect sensor measurements masked; missing values retained until train-only imputer. Regression target matching +/-60 seconds; classification uses actual future event timestamps.',
      'gate_policy':{'min_class_samples':{'train':50,'validation':10,'test_per_site':5},'min_f1':.65,'min_recall':.50,
         'min_site_f1':.55,'min_baseline_f1_gain':.02,'regression_min_mae_gain':.03,'all_heldout_sites_positive_gain':True},
      'features':features,'forbidden_features':sorted(FORBIDDEN),'input_csvs':sources,'models':[],
      'limitations':['Synthetic precursors and fault incidence are designed assumptions; no measured field fault ground truth.',
        'Rows are autocorrelated. Row count is NOT independent sample count.',
        'READY means this synthetic benchmark only; pilot requires real site-held-out data.',
        'Some outages may occur without precursors; predictor cannot replace observed connectivity rules.']}
    active={}
    for idx,spec in enumerate(SPECS):
        print('TRAIN',spec.name,flush=True)
        cols=[x for x in features if spec.task=='regression' or not x.startswith(('soil_moisture','temperature','ec','ph','air_humidity'))]
        assert not (set(cols)&FORBIDDEN)
        tr=frame.loc[train_mask].dropna(subset=[spec.target]);va=frame.loc[val_mask].dropna(subset=[spec.target]);te=frame.loc[test_mask].dropna(subset=[spec.target])
        if spec.metric:
            # Inference abstains without a valid current measurement. Evaluate that same domain.
            tr=tr.dropna(subset=[spec.metric]);va=va.dropna(subset=[spec.metric]);te=te.dropna(subset=[spec.metric])
            cols=[x for x in features if x==spec.metric or x.startswith(spec.metric+'_') or x=='history_gap_minutes']
        reasons=[];cov={}
        if spec.task=='classification':
            for split,part,minimum in [('train',tr,50),('validation',va,10),*[(str(k),v,5) for k,v in te.groupby('customer_id')]]:
                cov[split],ok=coverage(part,spec.target,minimum)
                if not ok:reasons.append('Missing class coverage in '+split)
        if min(len(tr),len(va),len(te))<100:reasons.append('Insufficient rows')
        entry={'name':spec.name,'title':spec.title,'task':spec.task,'target':spec.target,'horizon_minutes':spec.horizon_minutes,
          'class_coverage':cov,'train_rows':len(tr),'validation_rows':len(va),'test_rows':len(te),'features':cols,'scope':'simulation_only'}
        if reasons:
            entry.update(status='BLOCKED',gate_reasons=reasons);report['models'].append(entry);continue
        candidates={'hist_gradient_boosting':HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=15,l2_regularization=1,random_state=idx) if spec.task=='regression'
             else HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,l2_regularization=2,random_state=idx)}
        if spec.task=='regression':candidates['extra_trees']=ExtraTreesRegressor(n_estimators=60,min_samples_leaf=5,max_features=.8,n_jobs=2,random_state=idx)
        if spec.task=='regression':candidates['ridge_autoregression']=make_pipeline(StandardScaler(),Ridge(alpha=10))
        else:
            candidates['hist_gradient_boosting_detailed']=HistGradientBoostingClassifier(max_iter=200,max_leaf_nodes=15,l2_regularization=2,random_state=idx)
            candidates['hist_gradient_boosting_balanced']=HistGradientBoostingClassifier(max_iter=200,max_leaf_nodes=15,l2_regularization=2,class_weight='balanced',random_state=idx)
        evaluations={};fitted={}
        offset_train=tr[spec.metric].fillna(tr[spec.metric].median()).to_numpy() if spec.metric else 0
        offset_val=va[spec.metric].fillna(tr[spec.metric].median()).to_numpy() if spec.metric else 0
        for name,estimator in candidates.items():
            model=make_pipeline(SimpleImputer(add_indicator=True,keep_empty_features=True),VarianceThreshold(),estimator)
            model.fit(tr[cols],tr[spec.target].to_numpy()-offset_train)
            pred=model.predict(va[cols])+offset_val
            evaluations[name]=scores(va[spec.target],pred,spec.task);fitted[name]=model
        selected=min(evaluations,key=lambda k:evaluations[k]['mae']) if spec.metric else max(evaluations,key=lambda k:evaluations[k]['f1_macro'])
        model=fitted[selected];offset=te[spec.metric].fillna(tr[spec.metric].median()).to_numpy() if spec.metric else 0
        pred=model.predict(te[cols])+offset
        base=baselines(spec,te,tr);per_site={}
        for site,part in te.groupby('customer_id'):
            select=(te.customer_id==site).to_numpy();per_site[site]={'model':scores(part[spec.target],pred[select],spec.task),
                'baselines':{k:scores(part[spec.target],v[select],spec.task) for k,v in base.items()}}
        key='mae' if spec.metric else 'f1_macro'
        macro=float(np.mean([x['model'][key] for x in per_site.values()]))
        baseline_macro={k:float(np.mean([x['baselines'][k][key] for x in per_site.values()])) for k in base}
        if spec.metric:
            gain=1-macro/min(baseline_macro.values())
            if gain<.03:reasons.append('Macro MAE does not improve best baseline by 3%')
            if any(v['model']['mae']>=min(z['mae'] for z in v['baselines'].values()) for v in per_site.values()):reasons.append('Not better than baseline on every held-out site')
        else:
            gain=macro-max(baseline_macro.values())
            if macro<.65 or gain<.02:reasons.append('Macro F1 / baseline improvement gate failed')
            if any(v['model']['f1_macro']<.55 or v['model']['recall_risk']<.5 for v in per_site.values()):reasons.append('Held-out risk recall or F1 too low')
        prediction=pd.DataFrame({'customer_id':te.customer_id,'device_id':te.device_id,'observed_at':te.observed_at,'true':te[spec.target],'prediction':pred,**base})
        prediction.to_csv(out/(spec.name+'_predictions.csv'),index=False)
        entry.update(algorithm=selected,validation_candidates=evaluations,test_metrics=scores(te[spec.target],pred,spec.task),
          per_customer=per_site,macro_metric=macro,macro_metric_name=key,baseline_macro=baseline_macro,baseline_gain=gain,
          status='READY' if not reasons else 'EXPERIMENTAL',gate_reasons=reasons,
          prediction_csv=str(out/(spec.name+'_predictions.csv')),
          source_processed_csv=str(out/'processed_features_targets.csv'))
        path=out/(spec.name+'.joblib')
        joblib.dump({'pipeline':model,'features':cols,'metric':spec.metric,'offset_median':float(tr[spec.metric].median()) if spec.metric else 0,
             'horizon_minutes':spec.horizon_minutes,'dataset_version':run,'scope':'simulation_only','report':entry},path)
        entry['artifact_path']=str(path);entry['artifact_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        write_json(out/(spec.name+'_report.json'),entry)
        report['models'].append(entry)
        if not reasons:active[spec.name]=entry
        print(spec.name,entry['status'],'macro',round(macro,4),'gain',round(gain,4),flush=True)
    report['ready_count']=len(active);report['model_count']=len(SPECS)
    publish_registry(root,report,active)
    write_json(out/'training_report.json',report)
    pd.DataFrame([{k:m.get(k) for k in ['name','title','status','algorithm','macro_metric_name','macro_metric','baseline_gain','train_rows','validation_rows','test_rows']} for m in report['models']]).to_csv(out/'model_summary.csv',index=False)
    return report

def predict(root,sensor,status,source='synthetic_device_spec_v11'):
    manifest_path=Path(root)/'active_models.json'
    if not manifest_path.exists():return {'predictions':[],'reason':'Chưa có registry được kiểm định'}
    registry=json.loads(manifest_path.read_text(encoding='utf-8'))
    if source!='synthetic_device_spec_v11':return {'predictions':[],'reason':'Model chỉ kiểm định mô phỏng; cần validation dữ liệu thật trước khi áp dụng'}
    frame,_=prepare_features(pd.DataFrame(sensor),pd.DataFrame(status));last=frame.tail(1)
    results=[]
    for name,item in registry['models'].items():
        path=Path(item['artifact_path'])
        if not path.exists():path=Path(root)/'runs'/registry['dataset_version']/path.name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['artifact_sha256']:continue
        artifact=joblib.load(path);model=artifact['pipeline'];x=last[artifact['features']]
        if artifact['metric']:
            current=x[artifact['metric']].iloc[0]
            if pd.isna(current):continue
            value=float(model.predict(x)[0]+current)
        else:value=float(model.predict_proba(x)[0,1])
        results.append({'model':name,'title':item['title'],'value':value,'task':item['task'],
          'horizon_minutes':item['horizon_minutes'],'scope':'simulation_only','status':'READY',
          'observed_at':str(last.observed_at.iloc[0]),'dataset_version':registry['dataset_version']})
    return {'predictions':results,'production_ready':False,'dataset_version':registry['dataset_version']}
