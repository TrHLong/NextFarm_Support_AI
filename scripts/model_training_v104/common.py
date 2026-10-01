from __future__ import annotations
import hashlib, json, platform, shutil
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import joblib, sklearn
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    mean_absolute_error, mean_squared_error, r2_score,
    accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix, roc_auc_score, precision_recall_curve, roc_curve,
    classification_report
)

ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'data/simulation-30day-v103'
OUTROOT=ROOT/'model-artifacts/simulation-v104'
SEED=20260928
H=6  # 60 minutes at a 10-minute observation grid for incident look-ahead
BASE=['soil_moisture','temperature','air_humidity','ec','ph','flow_rate','moisture_lag_10m','moisture_lag_30m','moisture_lag_60m','moisture_lag_180m','moisture_mean_1h','moisture_std_1h','moisture_slope_1h','hour_sin','hour_cos']
DEVICE=['flow_rate','supply_voltage','rssi','pressure','pump_current','sensor_bus_errors','packet_loss_rate','command_failure_rate','pump_running','valve_running','online']


def utc_run_id():
    return datetime.now(timezone.utc).strftime('sim30-v104-%Y%m%dT%H%M%SZ')

def sha256(path:Path)->str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save_json(path:Path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

_RAW_CACHE=None
_FEATURE_CACHE=None

def load_raw()->pd.DataFrame:
    global _RAW_CACHE
    if _RAW_CACHE is not None:
        return _RAW_CACHE.copy()
    frames=[]
    for cdir in sorted((DATA/'customers').glob('synthetic_customer_*')):
        s=pd.read_csv(cdir/'sensor_readings.csv',parse_dates=['observed_at'])
        st=pd.read_csv(cdir/'device_status.csv',parse_dates=['observed_at'])
        gt=pd.read_csv(cdir/'incident_ground_truth.csv',parse_dates=['observed_at'])
        for x in (s,st,gt): x['observed_at']=pd.to_datetime(x['observed_at'],utc=True)
        keys=['customer_id','device_id','observed_at']
        df=s.merge(st,on=keys,how='left',suffixes=('','_status')).merge(gt,on=keys,how='left',suffixes=('','_truth'))
        df=df.sort_values('observed_at').reset_index(drop=True)
        # Causal short forward fill only for device state; never backfill future values.
        status_cols=['pump_running','valve_running','fertilizer_running','supply_voltage','rssi','pressure','pump_current','sensor_bus_errors','packet_loss_rate','command_failure_rate','online']
        for c in status_cols:
            if c in df.columns: df[c]=df[c].ffill(limit=2)
        frames.append(df)
    if not frames: raise RuntimeError(f'Không tìm thấy dữ liệu tại {DATA}')
    _RAW_CACHE=pd.concat(frames,ignore_index=True)
    return _RAW_CACHE.copy()

def build_features(raw:pd.DataFrame)->pd.DataFrame:
    global _FEATURE_CACHE
    if _FEATURE_CACHE is not None:
        return _FEATURE_CACHE.copy()
    df=raw.sort_values(['customer_id','observed_at']).copy()
    g=df.groupby('customer_id',sort=False)
    for lag in [1,3,6,18]: df[f'moisture_lag_{lag*10}m']=g.soil_moisture.shift(lag)
    df['moisture_mean_1h']=g.soil_moisture.transform(lambda x:x.rolling(6,min_periods=2).mean())
    df['moisture_std_1h']=g.soil_moisture.transform(lambda x:x.rolling(6,min_periods=2).std())
    df['moisture_slope_1h']=(df.soil_moisture-g.soil_moisture.shift(6))/60
    hr=df.observed_at.dt.hour+df.observed_at.dt.minute/60
    df['hour_sin']=np.sin(2*np.pi*hr/24); df['hour_cos']=np.cos(2*np.pi*hr/24)
    # 6-hour soil moisture target on 10-minute grid.
    df['target_moisture_6h']=g.soil_moisture.shift(-36)
    # 60-minute future incident labels from simulator ground truth.
    for name,cols in {'anomaly_60m':['no_flow','leak'],'maintenance_60m':['sensor_fault','power_loss','mqtt_loss']}.items():
        y=np.zeros(len(df),dtype=int)
        for _,idx in df.groupby('customer_id').groups.items():
            idx=np.array(list(idx)); p=df.loc[idx,cols].fillna(0).max(axis=1).to_numpy()
            future=pd.Series(p[::-1]).rolling(H,min_periods=1).max().to_numpy()[::-1]
            y[idx]=future.astype(int)
        df['target_'+name]=y
    # Explicit synthetic agronomic policy labels. These are not field ground truth.
    df['target_nutrient_action']=np.select(
        [(df.ec<1.45)|((df.ph<5.75)&(df.ec<1.8)),(df.ec>2.05)|(df.ph>6.75)],
        [2,0], default=1
    )
    deficit=np.maximum(0,65-df.soil_moisture)
    heat=np.maximum(0,df.temperature-28)
    dry=np.maximum(0,70-df.air_humidity)/20
    df['target_irrigation_minutes']=np.clip(4+0.75*deficit+0.55*heat+1.2*dry,4,35)
    _FEATURE_CACHE=df
    return _FEATURE_CACHE.copy()

def temporal_customer_split(df:pd.DataFrame):
    customers=sorted(df.customer_id.unique()); held=set(customers[-3:])
    start,end=df.observed_at.min(),df.observed_at.max(); c1=start+(end-start)*.70; c2=start+(end-start)*.85
    train=df[(~df.customer_id.isin(held))&(df.observed_at<c1)].copy()
    val=df[(~df.customer_id.isin(held))&(df.observed_at>=c1)&(df.observed_at<c2)].copy()
    test=df[(df.customer_id.isin(held))&(df.observed_at>=c2)].copy()
    meta={'start':start,'end':end,'train_end':c1,'validation_end':c2,'heldout_customers':sorted(held),
          'train_customers':sorted(train.customer_id.unique()),'test_customers':sorted(test.customer_id.unique())}
    return train,val,test,meta

def dataset_audit(raw,feat):
    origins={'SYNTHETIC_SIMULATION_ONLY':int(len(feat))}
    miss={c:float(feat[c].isna().mean()) for c in ['soil_moisture','temperature','air_humidity','ec','ph','flow_rate'] if c in feat}
    incidents={c:int(feat[c].fillna(0).sum()) for c in ['no_flow','leak','sensor_fault','power_loss','mqtt_loss'] if c in feat}
    return {
        'rows_raw':int(len(raw)),'rows_featured':int(len(feat)),'customers':int(feat.customer_id.nunique()),
        'devices':int(feat.device_id.nunique()),'start':feat.observed_at.min(),'end':feat.observed_at.max(),
        'duration_days':float((feat.observed_at.max()-feat.observed_at.min()).total_seconds()/86400),
        'duplicate_key_rows':int(feat.duplicated(['customer_id','device_id','observed_at']).sum()),
        'missing_fraction':miss,'incident_positive_rows':incidents,'origins':origins,
    }

def regression_metrics(y,p):
    ae=np.abs(np.asarray(y)-np.asarray(p))
    return {'mae':float(mean_absolute_error(y,p)),'rmse':float(mean_squared_error(y,p)**.5),'r2':float(r2_score(y,p)),
            'median_absolute_error':float(np.median(ae)),'p90_absolute_error':float(np.quantile(ae,.90))}

def classification_metrics(y,p,proba=None):
    out={'accuracy':float(accuracy_score(y,p)),
         'precision_macro':float(precision_score(y,p,average='macro',zero_division=0)),
         'recall_macro':float(recall_score(y,p,average='macro',zero_division=0)),
         'f1_macro':float(f1_score(y,p,average='macro',zero_division=0))}
    if proba is not None and len(np.unique(y))==2:
        try: out['roc_auc']=float(roc_auc_score(y,proba))
        except Exception: pass
    return out

def pipeline(estimator):
    return Pipeline([('imputer',SimpleImputer(strategy='median',add_indicator=True)),('model',estimator)])

def select_candidate(task,candidates,train,val,features,target):
    results=[]; best=None; best_score=None
    for name,est in candidates:
        p=pipeline(est); p.fit(train[features],train[target]); pv=p.predict(val[features])
        if task=='regression':
            m=regression_metrics(val[target],pv); score=m['mae']; better=best_score is None or score<best_score
        else:
            prob=p.predict_proba(val[features]) if hasattr(p,'predict_proba') else None
            m=classification_metrics(val[target],pv,prob[:,1] if prob is not None and prob.shape[1]==2 else None); score=m['f1_macro']; better=best_score is None or score>best_score
        results.append({'candidate':name,'validation_metrics':m})
        if better: best=(name,p); best_score=score
    return best,results

def feature_importance(pipe,features):
    model=pipe.named_steps['model']
    vals=getattr(model,'feature_importances_',None)
    if vals is None: return None
    vals=np.asarray(vals)[:len(features)]
    return pd.DataFrame({'feature':features,'importance':vals}).sort_values('importance',ascending=False)

def save_model_artifact(out_dir:Path,name:str,pipe,features,target,task,label_mapping=None):
    obj={'pipeline':pipe,'features':features,'target':target,'task':task,'scope':'SYNTHETIC_SIMULATION_ONLY',
         'status':'EXPERIMENTAL_SIMULATION','model_name':name,'label_mapping':label_mapping}
    mdir=out_dir/'models'; mdir.mkdir(parents=True,exist_ok=True)
    job=mdir/f'{name}.joblib'; joblib.dump(obj,job,compress=3); shutil.copy2(job,mdir/f'{name}.pkl')
    return job,obj

def plot_regression(out_dir,name,y,p,timestamps=None):
    c=out_dir/'charts'; c.mkdir(parents=True,exist_ok=True); paths={}
    plt.figure(figsize=(6,5)); plt.scatter(y,p,s=8,alpha=.35); lo=min(float(np.min(y)),float(np.min(p))); hi=max(float(np.max(y)),float(np.max(p))); plt.plot([lo,hi],[lo,hi]); plt.xlabel('Actual'); plt.ylabel('Predicted'); plt.title(name+' - Actual vs Predicted'); plt.tight_layout(); q=c/f'{name}_actual_pred.png'; plt.savefig(q,dpi=160); plt.close(); paths['actual_pred']=str(q)
    resid=np.asarray(p)-np.asarray(y); plt.figure(figsize=(6,4)); plt.hist(resid,bins=40); plt.axvline(0); plt.xlabel('Prediction - Actual'); plt.ylabel('Count'); plt.title(name+' - Residual Distribution'); plt.tight_layout(); q=c/f'{name}_residuals.png'; plt.savefig(q,dpi=160); plt.close(); paths['residuals']=str(q)
    n=min(300,len(y)); plt.figure(figsize=(8,3.8)); plt.plot(np.asarray(y)[-n:],label='Actual'); plt.plot(np.asarray(p)[-n:],label='Predicted'); plt.legend(); plt.xlabel('Ordered test sample'); plt.ylabel('Target'); plt.title(name+' - Test Sequence'); plt.tight_layout(); q=c/f'{name}_sequence.png'; plt.savefig(q,dpi=160); plt.close(); paths['sequence']=str(q)
    return paths

def plot_classification(out_dir,name,y,p,proba=None,labels=None):
    c=out_dir/'charts'; c.mkdir(parents=True,exist_ok=True); paths={}
    cm=confusion_matrix(y,p,labels=labels)
    plt.figure(figsize=(5.4,4.6)); plt.imshow(cm); plt.title(name+' - Confusion Matrix'); plt.xlabel('Predicted'); plt.ylabel('Actual');
    for (i,j),v in np.ndenumerate(cm): plt.text(j,i,str(v),ha='center',va='center')
    if labels is not None: plt.xticks(range(len(labels)),labels); plt.yticks(range(len(labels)),labels)
    plt.tight_layout(); q=c/f'{name}_confusion.png'; plt.savefig(q,dpi=160); plt.close(); paths['confusion']=str(q)
    if proba is not None and len(np.unique(y))==2:
        fpr,tpr,_=roc_curve(y,proba); plt.figure(figsize=(5.4,4)); plt.plot(fpr,tpr); plt.plot([0,1],[0,1],'--'); plt.xlabel('False positive rate'); plt.ylabel('True positive rate'); plt.title(name+' - ROC'); plt.tight_layout(); q=c/f'{name}_roc.png'; plt.savefig(q,dpi=160); plt.close(); paths['roc']=str(q)
        pr,rc,_=precision_recall_curve(y,proba); plt.figure(figsize=(5.4,4)); plt.plot(rc,pr); plt.xlabel('Recall'); plt.ylabel('Precision'); plt.title(name+' - Precision Recall'); plt.tight_layout(); q=c/f'{name}_pr.png'; plt.savefig(q,dpi=160); plt.close(); paths['pr']=str(q)
    return paths

def plot_importance(out_dir,name,imp):
    if imp is None or imp.empty: return None
    c=out_dir/'charts'; c.mkdir(parents=True,exist_ok=True); top=imp.head(15).sort_values('importance')
    plt.figure(figsize=(7,5)); plt.barh(top.feature,top.importance); plt.xlabel('Importance'); plt.title(name+' - Feature Importance'); plt.tight_layout(); q=c/f'{name}_feature_importance.png'; plt.savefig(q,dpi=160); plt.close(); return str(q)

def environment():
    return {'python':platform.python_version(),'sklearn':sklearn.__version__,'pandas':pd.__version__,'numpy':np.__version__}
