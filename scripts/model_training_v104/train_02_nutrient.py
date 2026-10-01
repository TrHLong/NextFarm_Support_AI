from __future__ import annotations
import argparse, json
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from common import *
MODEL_NAME='nutrient_recommendation'; TASK='classification'; TARGET='target_nutrient_action'
FEATURES=['ec','ph','soil_moisture','temperature','air_humidity','flow_rate','hour_sin','hour_cos']
OBJECTIVE='Phân loại hành động châm dinh dưỡng mô phỏng thành REDUCE / KEEP / INCREASE dựa trên EC, pH và điều kiện cảm biến.'
ALGORITHM_RATIONALE=('Random Forest và Extra Trees được benchmark vì phù hợp cho luật dinh dưỡng phi tuyến, tương tác EC-pH và không yêu cầu chuẩn hóa. '
'Model cuối được chọn bằng Macro-F1 trên Validation để tránh Accuracy cao giả tạo khi lớp KEEP chiếm đa số. Đây là nhãn policy mô phỏng, không phải khuyến cáo nông học ngoài thực địa.')

def run(out_dir:Path):
 raw=load_raw(); df=build_features(raw); tr,va,te,split=temporal_customer_split(df)
 candidates=[('RandomForestClassifier',RandomForestClassifier(n_estimators=60,min_samples_leaf=3,class_weight='balanced',n_jobs=-1,random_state=SEED)),('ExtraTreesClassifier',ExtraTreesClassifier(n_estimators=60,min_samples_leaf=3,class_weight='balanced',n_jobs=-1,random_state=SEED))]
 (selected,pipe),comparison=select_candidate(TASK,candidates,tr,va,FEATURES,TARGET); pred=pipe.predict(te[FEATURES]); prob=pipe.predict_proba(te[FEATURES]) if hasattr(pipe,'predict_proba') else None; metrics=classification_metrics(te[TARGET],pred,None)
 mapping={'0':'REDUCE','1':'KEEP','2':'INCREASE'}; job,_=save_model_artifact(out_dir,MODEL_NAME,pipe,FEATURES,TARGET,TASK,mapping)
 import pandas as pd; pdir=out_dir/'predictions'; pdir.mkdir(parents=True,exist_ok=True); predcsv=pdir/f'{MODEL_NAME}_test_predictions.csv'; pd.DataFrame({'observed_at':te.observed_at.astype(str),'customer_id':te.customer_id,'actual':te[TARGET].to_numpy(),'prediction':pred}).to_csv(predcsv,index=False)
 charts=plot_classification(out_dir,MODEL_NAME,te[TARGET].to_numpy(),pred,labels=[0,1,2]); imp=feature_importance(pipe,FEATURES); fi=plot_importance(out_dir,MODEL_NAME,imp)
 rep=classification_report(te[TARGET],pred,labels=[0,1,2],target_names=['REDUCE','KEEP','INCREASE'],zero_division=0,output_dict=True)
 return {'model':MODEL_NAME,'objective':OBJECTIVE,'algorithm_rationale':ALGORITHM_RATIONALE,'task':TASK,'target':TARGET,'features':FEATURES,'selected_algorithm':selected,'candidate_validation':comparison,'test_metrics':metrics,'classification_report':rep,'class_distribution':{str(k):int(v) for k,v in te[TARGET].value_counts().sort_index().items()},'rows':{'train':len(tr),'validation':len(va),'test':len(te)},'split':split,'artifact':str(job),'sha256':sha256(job),'predictions':str(predcsv),'charts':{**charts,'feature_importance':fi},'feature_importance':imp.to_dict('records') if imp is not None else []}
if __name__=='__main__':
 a=argparse.ArgumentParser(); a.add_argument('--out',required=True); x=a.parse_args(); print(json.dumps(run(Path(x.out)),ensure_ascii=False,indent=2,default=str))
