from __future__ import annotations
import argparse,json
from pathlib import Path
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier, HistGradientBoostingClassifier
from common import *
MODEL_NAME='predictive_maintenance'; TASK='classification'; TARGET='target_maintenance_60m'; FEATURES=DEVICE
OBJECTIVE='Dự đoán nguy cơ sensor fault, mất nguồn hoặc mất MQTT trong 60 phút tới từ telemetry sức khỏe thiết bị.'
ALGORITHM_RATIONALE=('Predictive maintenance có tín hiệu phi tuyến và tương tác mạnh giữa voltage, RSSI, packet loss, command failure, current và online state. '
'Extra Trees và Random Forest được benchmark vì robust trên dữ liệu bảng, không cần scaling và giải thích được feature importance; Macro-F1 là tiêu chí chọn để không bỏ qua lớp sự cố hiếm.')

def run(out_dir:Path):
 raw=load_raw(); df=build_features(raw); tr,va,te,split=temporal_customer_split(df)
 candidates=[('ExtraTreesClassifier',ExtraTreesClassifier(n_estimators=60,min_samples_leaf=2,class_weight='balanced',n_jobs=-1,random_state=SEED)),('RandomForestClassifier',RandomForestClassifier(n_estimators=60,min_samples_leaf=2,class_weight='balanced',n_jobs=-1,random_state=SEED))]
 (selected,pipe),comparison=select_candidate(TASK,candidates,tr,va,FEATURES,TARGET); pred=pipe.predict(te[FEATURES]); prob=pipe.predict_proba(te[FEATURES])[:,1] if hasattr(pipe,'predict_proba') else None; metrics=classification_metrics(te[TARGET],pred,prob); job,_=save_model_artifact(out_dir,MODEL_NAME,pipe,FEATURES,TARGET,TASK)
 import pandas as pd; pdir=out_dir/'predictions'; pdir.mkdir(parents=True,exist_ok=True); predcsv=pdir/f'{MODEL_NAME}_test_predictions.csv'; pd.DataFrame({'observed_at':te.observed_at.astype(str),'customer_id':te.customer_id,'actual':te[TARGET].to_numpy(),'prediction':pred,'probability':prob}).to_csv(predcsv,index=False)
 charts=plot_classification(out_dir,MODEL_NAME,te[TARGET].to_numpy(),pred,prob,labels=[0,1]); imp=feature_importance(pipe,FEATURES); fi=plot_importance(out_dir,MODEL_NAME,imp); rep=classification_report(te[TARGET],pred,labels=[0,1],target_names=['NORMAL','MAINTENANCE_RISK'],zero_division=0,output_dict=True)
 return {'model':MODEL_NAME,'objective':OBJECTIVE,'algorithm_rationale':ALGORITHM_RATIONALE,'task':TASK,'target':TARGET,'features':FEATURES,'selected_algorithm':selected,'candidate_validation':comparison,'test_metrics':metrics,'classification_report':rep,'class_distribution':{str(k):int(v) for k,v in te[TARGET].value_counts().sort_index().items()},'rows':{'train':len(tr),'validation':len(va),'test':len(te)},'split':split,'artifact':str(job),'sha256':sha256(job),'predictions':str(predcsv),'charts':{**charts,'feature_importance':fi},'feature_importance':imp.to_dict('records') if imp is not None else []}
if __name__=='__main__':
 a=argparse.ArgumentParser(); a.add_argument('--out',required=True); x=a.parse_args(); print(json.dumps(run(Path(x.out)),ensure_ascii=False,indent=2,default=str))
