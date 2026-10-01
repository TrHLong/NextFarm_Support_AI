"""Fit actual estimators on sealed 72h runtime CSVs, without a fabricated READY claim."""
import json,hashlib,shutil
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd
import numpy as np
import joblib
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.feature_selection import VarianceThreshold
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor,HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from .contracts import ACTIVE_SPECS
from .collection import VERSION
from .data_quality import CLEANING_VERSION
from .ml import prepare_features,scores,baselines,coverage,write_json
from .forecast_acceptance import POLICY,regression_acceptance,classification_acceptance

def seal_frame(snapshot):
    snapshot=Path(snapshot);manifest=json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('contract')!=VERSION or manifest.get('backfill_allowed') is not False:raise ValueError('Only sealed runtime snapshots accepted')
    if manifest.get('cleaning_version')!=CLEANING_VERSION:raise ValueError('Snapshot must use current audited cleaning rules')
    if manifest.get('acquisition_hours',0)<72 or not any(g.get('eligible') and g.get('elapsed_received_hours',0)>=72 for g in manifest.get('gates',{}).values()):raise ValueError('No verified 72h acquisition gate')
    for record in manifest['files']:
        path=(snapshot/record['path']).resolve()
        if not path.is_relative_to(snapshot.resolve()):raise ValueError('CSV outside sealed snapshot')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('CSV checksum mismatch')
    frames=[];features=None
    for record in manifest['files']:
        if record['stage']!='cleaned' or record['group']!='sensor_readings':continue
        folder=(snapshot/record['path']).parent;s=pd.read_csv(folder/'sensor_readings.csv');d=pd.read_csv(folder/'device_status.csv')
        if s.empty or d.empty:continue
        for df in [s,d]:
            for k in ['observed_at','received_at']:df[k]=pd.to_datetime(df[k],utc=True,format='ISO8601')
        s=s.loc[(s.received_at-s.observed_at).dt.total_seconds().between(-30,60)].copy()
        d=d.loc[(d.received_at-d.observed_at).dt.total_seconds().between(-30,30)].copy()
        # Historical evidence must have arrived before the decision timestamp.
        for df in [s,d]:df['observed_at']=df[['observed_at','received_at']].max(axis=1)
        frame,features=prepare_features(s,d);frame=frame.copy();origin=s.set_index('observed_at').sort_index()
        truth=pd.read_csv(folder/'incident_ground_truth.csv')
        if not truth.empty:truth['observed_at']=pd.to_datetime(truth.observed_at,utc=True,format='ISO8601');truth=truth.sort_values('observed_at').drop_duplicates('observed_at')
        for spec in ACTIVE_SPECS:
            frame[spec.target]=np.nan
            if spec.metric:
                future=pd.merge_asof(pd.DataFrame({'at':frame.observed_at+pd.Timedelta(minutes=30)}),origin[[spec.metric]].reset_index().rename(columns={'observed_at':'at'}),on='at',direction='nearest',tolerance=pd.Timedelta(seconds=90))
                frame[spec.target]=future[spec.metric].to_numpy()
            elif not truth.empty:
                key=spec.target.removesuffix('_future')
                if key not in truth:continue
                series=pd.to_numeric(truth[key],errors='coerce').where(truth.get('ground_truth_origin',pd.Series('',index=truth.index)).isin(['synthetic_latent_incident','reviewed_independent_incident']));at=truth.observed_at
                for idx,observed in enumerate(frame.observed_at):
                    current=series.loc[(at<=observed)&(at>observed-pd.Timedelta(minutes=11))]
                    horizon=series.loc[(at>observed)&(at<=observed+pd.Timedelta(minutes=60))]
                    horizon_at=at.loc[horizon.index]
                    full_window=len(horizon)>=6 and (horizon_at.iloc[-1]-observed)>=pd.Timedelta(minutes=49) and horizon_at.diff().dropna().max()<=pd.Timedelta(minutes=11)
                    if len(current) and current.iloc[-1]==0 and full_window and horizon.notna().all():frame.loc[frame.index[idx],spec.target]=int((horizon==1).any())
        frame['device_id']=record['device_id'];frame['customer_id']=record['customer_id'];frame['label_end']=frame.observed_at+pd.Timedelta(minutes=60);frames.append(frame)
    return (pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()),features,manifest

def train_snapshot(snapshot,artifact_root):
    import sklearn,platform
    snapshot=Path(snapshot);root=Path(artifact_root);frame,features,manifest=seal_frame(snapshot)
    run=root/'runs'/snapshot.name;run.mkdir(parents=True,exist_ok=False);code=run/'training_code';code.mkdir()
    for file in ['runtime_training.py','collection.py','data_quality.py','ml.py','contracts.py','forecast_acceptance.py']:shutil.copy2(Path(__file__).parent/file,code/file)
    report={'dataset_version':snapshot.name,'source_manifest':str(snapshot/'manifest.json'),'data_origin':manifest['data_sources'],'train_executed':False,
      'field_validation':False,'status':'BLOCKED','production_ready':False,'ready_count':0,'models':[],'contract':VERSION,'created_at':datetime.now(timezone.utc).isoformat(),'reasons':[],
      'limitations':['72 hours is an initial experiment, not seasonal/field validation.','Runtime simulator remains synthetic.','No forecast served until independent pilot acceptance.']}
    report['environment']={'python':platform.python_version(),'sklearn':sklearn.__version__,'pandas':pd.__version__,'numpy':np.__version__,'random_state':17}
    report['manifest_sha256']=hashlib.sha256((snapshot/'manifest.json').read_bytes()).hexdigest()
    report['cleaning_version']=CLEANING_VERSION
    report['proposed_acceptance_policy']=POLICY
    report['training_code_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in code.glob('*.py')}
    customers=sorted(frame.customer_id.unique()) if not frame.empty else []
    if len(customers)<3:
        report['reasons']=['Cần ít nhất 3 khách để dành riêng một khách test; không train riêng cho từng khách']
        report['models']=[{'name':s.name,'title':s.title,'status':'BLOCKED','gate_reasons':report['reasons']} for s in ACTIVE_SPECS]
        write_training_evidence(run,root,report);return report
    test_customer=customers[-1];development=customers[:-1]
    start=max(pd.Timestamp(g['window_start']) for g in manifest['gates'].values() if g['eligible']);end=min(pd.Timestamp(g['window_end']) for g in manifest['gates'].values() if g['eligible'])
    if end-start<pd.Timedelta(hours=71.5):
        report['reasons']=['Các cửa sổ 72 giờ theo khách chưa giao nhau đủ 71.5 giờ; chờ vòng thu tiếp theo']
        report['models']=[{'name':s.name,'title':s.title,'status':'BLOCKED','gate_reasons':report['reasons']} for s in ACTIVE_SPECS]
        write_training_evidence(run,root,report);return report
    train_cut=start+pd.Timedelta(hours=36);test_cut=start+pd.Timedelta(hours=48)
    frame['split']='excluded_or_purged'
    frame.loc[frame.customer_id.isin(development)&(frame.observed_at>=start)&(frame.label_end<train_cut),'split']='train'
    frame.loc[frame.customer_id.isin(development)&(frame.observed_at>=train_cut)&(frame.label_end<test_cut),'split']='validation'
    frame.loc[(frame.customer_id==test_customer)&(frame.observed_at>=test_cut)&(frame.label_end<=end),'split']='test_unseen_customer'
    frame.to_csv(run/'features_and_splits.csv',index=False)
    report.update(held_out_customer=test_customer,development_customers=development,split_counts=frame.split.value_counts().to_dict(),train_cut=train_cut.isoformat(),test_cut=test_cut.isoformat(),window_end=end.isoformat(),features=features,
      preprocessing='Fixed cleaning first; causal lags; purge target end; imputer/scaler/variance filter fit train only',selection='Validation only; no refit after test',reasons=['Exploratory 72h benchmark only; no field pilot validation'])
    for spec in ACTIVE_SPECS:
        fields=[x for x in features if x==spec.metric or x.startswith(spec.metric+'_') or x=='history_gap_minutes'] if spec.metric else [x for x in features if not any(x.startswith(k) for k in ['soil_moisture','temperature','ec','ph','air_humidity'])]
        parts={k:frame.loc[frame.split==k].dropna(subset=[spec.target]+([spec.metric] if spec.metric else [])) for k in ['train','validation','test_unseen_customer']}
        tr,va,te=parts.values();reasons=[];entry={'name':spec.name,'title':spec.title,'task':spec.task,'target':spec.target,'features':fields,'csv_manifest':str(snapshot/'manifest.json'),'processed_csv':str(run/'features_and_splits.csv'),
          'rows':{k:len(v) for k,v in parts.items()},'trained':False,'status':'BLOCKED','scope':'runtime_experiment',
          'raw_csvs':[f['path'] for f in manifest['files'] if f['stage']=='raw' and f['group'] in (['sensor_readings','device_status'] if spec.metric else ['sensor_readings','device_status','incident_ground_truth'])],
          'interpretation':'MAE/RMSE: sai số theo đơn vị gốc; R2 không phải phần trăm chính xác.' if spec.metric else 'Accuracy đi kèm F1-macro, recall lớp sự cố và ma trận nhầm lẫn. Dòng có tương quan không phải sự cố độc lập.'}
        if any(len(parts[k])<n for k,n in [('train',100),('validation',24),('test_unseen_customer',24)]):reasons.append('Không đủ target hợp lệ sau làm sạch và purge')
        if not spec.metric:
            entry['class_coverage']={}
            for key,n in [('train',50),('validation',10),('test_unseen_customer',5)]:
                counts,ok=coverage(parts[key],spec.target,n);entry['class_coverage'][key]=counts
                if not ok:reasons.append('Thiếu nhãn/lớp sự cố độc lập trong '+key)
            # Positive rows from one incident are correlated. Count separate positive
            # windows conservatively; this still is not a substitute for field incidents.
            entry['positive_episodes']={}
            for key,minimum in [('train',5),('validation',2),('test_unseen_customer',2)]:
                episodes=0
                for _,part in parts[key].groupby('device_id'):
                    labels=part.sort_values('observed_at')[spec.target]
                    episodes+=int(((labels==1)&(labels.shift(1,fill_value=0)==0)).sum())
                entry['positive_episodes'][key]=episodes
                if episodes<minimum:reasons.append('Quá ít đợt nhãn dương tách biệt trong '+key)
        if reasons:entry['gate_reasons']=reasons;report['models'].append(entry);continue
        models={'ridge':make_pipeline(StandardScaler(),Ridge(alpha=10)),'hist_gradient_boosting':HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=15,random_state=17)} if spec.metric else {'hist_gradient_boosting':HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,random_state=17)}
        fitted={};validation={};offset_train=tr[spec.metric].to_numpy() if spec.metric else 0;offset_val=va[spec.metric].to_numpy() if spec.metric else 0
        for name,est in models.items():
            try:
                pipe=make_pipeline(SimpleImputer(strategy="median",add_indicator=True,keep_empty_features=True),VarianceThreshold(),est);pipe.fit(tr[fields],tr[spec.target]-offset_train);fitted[name]=pipe
                validation[name]=scores(va[spec.target],pipe.predict(va[fields])+offset_val,spec.task)
            except ValueError as exc:entry.setdefault('candidate_errors',{})[name]=str(exc)
        if not validation:
            entry['gate_reasons']=['Không fit được ứng viên; xem candidate_errors, không có kết quả test'];report['models'].append(entry);continue
        chosen=min(validation,key=lambda x:validation[x]['mae']) if spec.metric else max(validation,key=lambda x:validation[x]['f1_macro'])
        pipe=fitted[chosen];pred=pipe.predict(te[fields])+(te[spec.metric].to_numpy() if spec.metric else 0)
        baseline=baselines(spec,te,tr);metric=scores(te[spec.target],pred,spec.task);base_scores={k:scores(te[spec.target],v,spec.task) for k,v in baseline.items()}
        gain=regression_gain(metric['mae'],min(x['mae'] for x in base_scores.values())) if spec.metric else metric['f1_macro']-max(x['f1_macro'] for x in base_scores.values())
        acceptance=regression_acceptance(te[spec.target],pred,spec.metric,int(((frame.split=='test_unseen_customer')&frame[spec.target].notna()).sum())) if spec.metric else classification_acceptance(metric['confusion_matrix'],metric['f1_macro'],metric['recall_risk'])
        passed=acceptance['numeric_gate_passed'] and gain>=(.03 if spec.metric else .02)
        entry['proposed_acceptance']=acceptance
        importance=permutation_importance(pipe,va[fields],va[spec.target]-offset_val,n_repeats=3,random_state=17,scoring='neg_mean_absolute_error' if spec.metric else 'f1_macro')
        entry.update(trained=True,status='EXPERIMENTAL',algorithm=chosen,validation_candidates=validation,test_metrics=metric,baseline_metrics=base_scores,baseline_gain=gain,benchmark_gate_passed=bool(passed),per_customer={test_customer:metric},
          validation_feature_importance=sorted([{'feature':f,'importance':float(v)} for f,v in zip(fields,importance.importances_mean)],key=lambda x:x['importance'],reverse=True),gate_reasons=([] if passed else ['Chưa vượt baseline hoặc recall tối thiểu'])+['Chưa có nghiệm thu pilot; không gắn READY'])
        predictions=te[['customer_id','device_id','observed_at',spec.target]].copy();predictions['prediction']=pred
        for key,value in baseline.items():predictions[key]=value
        if not spec.metric:predictions['risk_probability_uncalibrated']=pipe.predict_proba(te[fields])[:,1]
        worst=np.argsort(np.abs(te[spec.target].to_numpy()-pred))[-10:][::-1];predictions.iloc[worst].to_csv(run/(spec.name+'_failure_cases.csv'),index=False);predictions.to_csv(run/(spec.name+'_test_predictions.csv'),index=False)
        path=run/(spec.name+'.joblib');joblib.dump({'pipeline':pipe,'features':fields,'metric':spec.metric,'scope':'runtime_experiment'},path)
        assert np.allclose(joblib.load(path)['pipeline'].predict(te[fields]),pipe.predict(te[fields]))
        entry.update(artifact=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),export_parity_verified=True);write_json(run/(spec.name+'_report.json'),entry);report['models'].append(entry)
    report.update(status='EXPERIMENTAL' if any(m['trained'] for m in report['models']) else 'BLOCKED',train_executed=any(m['trained'] for m in report['models']),trained_count=sum(m['trained'] for m in report['models']),benchmark_pass_count=sum(m.get('benchmark_gate_passed',False) for m in report['models']))
    write_training_evidence(run,root,report)
    return report


def regression_gain(mae,baseline_mae):
    # Equal perfect predictions do not constitute an improvement over persistence.
    if baseline_mae<=1e-12:return 0.0 if mae<=1e-12 else -1.0
    return 1-mae/baseline_mae


def write_training_evidence(run,root,report):
    """Readable, self-contained reports even when all ten jobs are blocked."""
    import html
    write_json(run/'training_report.json',report);write_json(root/'latest_training_report.json',report)
    for entry in report['models']:write_json(run/(entry['name']+'_report.json'),entry)
    pd.DataFrame([{'model':m['name'],'trained':m.get('trained',False),'status':m['status'],'gate_passed':m.get('benchmark_gate_passed'),**m.get('rows',{})} for m in report['models']]).to_csv(run/'model_summary.csv',index=False)
    esc=lambda v:html.escape(str(v));rows=[]
    for m in report['models']:
        rows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [m['title'],m['status'],m.get('algorithm','Chưa train'),m.get('rows',{}),m.get('test_metrics','Chưa có kết quả test'),'; '.join(m.get('gate_reasons',[]))])+'</tr>')
    text='''<!doctype html><html lang="vi"><meta charset="utf-8"><title>Báo cáo huấn luyện</title><style>body{font:16px Arial;margin:36px;color:#15352b}table{border-collapse:collapse;width:100%}td,th{border:1px solid #bacac1;padding:10px;text-align:left;vertical-align:top}th{background:#e7f2ec}pre{white-space:pre-wrap}</style><h1>Kết quả huấn luyện từ CSV vận hành</h1>'''
    text+='<p>Bộ dữ liệu: '+esc(report['dataset_version'])+'. Manifest: '+esc(report['source_manifest'])+'</p>'
    text+='<p>Đây là thí nghiệm ban đầu. 72 giờ thu mô phỏng không chứng minh chất lượng ngoài thực địa. READY: 0. Không phát hành dự báo chưa nghiệm thu.</p>'
    text+='<p>Làm sạch theo quy tắc cố định → tạo đặc trưng quá khứ → chia 36 giờ train / 12 giờ validation / khoảng 24 giờ test ở khách giữ riêng → loại nhãn chạm ranh giới → fit imputer/scaler trên train → chọn bằng validation → đánh giá test một lần → xuất ứng viên và kiểm tra nạp lại.</p>'
    text+='<table><tr><th>Model</th><th>Trạng thái</th><th>Thuật toán</th><th>Số dòng sau lọc/chia</th><th>Test</th><th>Giải thích / lý do chặn</th></tr>'+''.join(rows)+'</table>'
    text+='<h2>Cách đọc số liệu và tái lập</h2><p>MAE/RMSE có đơn vị của cảm biến, càng nhỏ càng tốt. R² không phải % chính xác. Phân loại xem đồng thời F1-macro, recall và confusion matrix; nhiều dòng của cùng sự cố không phải nhiều sự cố độc lập. Mỗi *_report.json ghi rõ CSV nguồn, đặc trưng, baseline, ngưỡng, kết quả và lý do chặn. *_test_predictions.csv lưu từng dự đoán đối chiếu nhãn; *_failure_cases.csv lưu lỗi lớn nhất. features_and_splits.csv giữ mã khách/tủ để truy vết nhưng các mã không vào đặc trưng. training_code lưu mã nguồn dùng trong lần chạy.</p>'
    (run/'training_report.html').write_text(text,encoding='utf-8')
