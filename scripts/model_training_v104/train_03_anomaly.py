from __future__ import annotations
import argparse,json
from pathlib import Path
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier, HistGradientBoostingClassifier
from common import *
MODEL_NAME='anomaly_detection'; TASK='classification'; TARGET='target_anomaly_60m'; FEATURES=DEVICE
OBJECTIVE='Phát hiện/nghi ngờ sự cố no-flow hoặc leak trong 60 phút tới từ trạng thái van/bơm, lưu lượng và telemetry thiết bị.'
ALGORITHM_RATIONALE=('Extra Trees và Random Forest được benchmark vì anomaly ở đây có ground-truth nhị phân và quan hệ điều kiện kiểu van-bơm-flow rất phi tuyến. '
'Macro-F1 được dùng để chọn model nhằm cân bằng lớp bình thường và lớp sự cố; ROC-AUC chỉ là metric bổ sung.')

def run(out_dir:Path):
 raw=load_raw(); df=build_features(raw); tr,va,te,split=temporal_customer_split(df)
 candidates=[('ExtraTreesClassifier',ExtraTreesClassifier(n_estimators=60,min_samples_leaf=2,class_weight='balanced',n_jobs=-1,random_state=SEED)),('RandomForestClassifier',RandomForestClassifier(n_estimators=60,min_samples_leaf=2,class_weight='balanced',n_jobs=-1,random_state=SEED))]
 (selected,pipe),comparison=select_candidate(TASK,candidates,tr,va,FEATURES,TARGET); pred=pipe.predict(te[FEATURES]); prob=pipe.predict_proba(te[FEATURES])[:,1] if hasattr(pipe,'predict_proba') else None; metrics=classification_metrics(te[TARGET],pred,prob)
 job,_=save_model_artifact(out_dir,MODEL_NAME,pipe,FEATURES,TARGET,TASK); import pandas as pd; pdir=out_dir/'predictions'; pdir.mkdir(parents=True,exist_ok=True); predcsv=pdir/f'{MODEL_NAME}_test_predictions.csv'; pd.DataFrame({'observed_at':te.observed_at.astype(str),'customer_id':te.customer_id,'actual':te[TARGET].to_numpy(),'prediction':pred,'probability':prob}).to_csv(predcsv,index=False)
 charts=plot_classification(out_dir,MODEL_NAME,te[TARGET].to_numpy(),pred,prob,labels=[0,1]); imp=feature_importance(pipe,FEATURES); fi=plot_importance(out_dir,MODEL_NAME,imp); rep=classification_report(te[TARGET],pred,labels=[0,1],target_names=['NORMAL','ANOMALY'],zero_division=0,output_dict=True)
 return {'model':MODEL_NAME,'objective':OBJECTIVE,'algorithm_rationale':ALGORITHM_RATIONALE,'task':TASK,'target':TARGET,'features':FEATURES,'selected_algorithm':selected,'candidate_validation':comparison,'test_metrics':metrics,'classification_report':rep,'class_distribution':{str(k):int(v) for k,v in te[TARGET].value_counts().sort_index().items()},'rows':{'train':len(tr),'validation':len(va),'test':len(te)},'split':split,'artifact':str(job),'sha256':sha256(job),'predictions':str(predcsv),'charts':{**charts,'feature_importance':fi},'feature_importance':imp.to_dict('records') if imp is not None else []}
if __name__=='__main__':
 a=argparse.ArgumentParser(); a.add_argument('--out',required=True); x=a.parse_args(); print(json.dumps(run(Path(x.out)),ensure_ascii=False,indent=2,default=str))
