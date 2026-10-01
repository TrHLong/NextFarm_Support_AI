from __future__ import annotations
import argparse, json
from pathlib import Path
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor, HistGradientBoostingRegressor
from common import *
MODEL_NAME='soil_moisture_forecast'
OBJECTIVE='Dự báo độ ẩm đất sau 6 giờ từ chuỗi cảm biến và trạng thái môi trường gần nhất.'
ALGORITHM_RATIONALE=('Extra Trees và Random Forest được benchmark vì bài toán là hồi quy phi tuyến trên dữ liệu cảm biến dạng bảng với nhiều tương tác và lag. '
'Extra Trees đặc biệt phù hợp giai đoạn mô phỏng vì không cần scaling, chịu được quan hệ phi tuyến và cho phép giải thích feature importance. Thuật toán cuối cùng chỉ được chọn theo MAE Validation, Test không dùng để chọn model.')
FEATURES=BASE; TARGET='target_moisture_6h'; TASK='regression'

def run(out_dir:Path):
 raw=load_raw(); df=build_features(raw); tr,va,te,split=temporal_customer_split(df); tr=tr.dropna(subset=[TARGET]); va=va.dropna(subset=[TARGET]); te=te.dropna(subset=[TARGET])
 candidates=[('ExtraTreesRegressor',ExtraTreesRegressor(n_estimators=60,min_samples_leaf=3,max_features=.85,n_jobs=-1,random_state=SEED)),('RandomForestRegressor',RandomForestRegressor(n_estimators=60,min_samples_leaf=3,max_features=.85,n_jobs=-1,random_state=SEED))]
 (selected,pipe),comparison=select_candidate(TASK,candidates,tr,va,FEATURES,TARGET); pred=pipe.predict(te[FEATURES]); metrics=regression_metrics(te[TARGET],pred)
 job,_=save_model_artifact(out_dir,MODEL_NAME,pipe,FEATURES,TARGET,TASK); pdir=out_dir/'predictions'; pdir.mkdir(parents=True,exist_ok=True); predcsv=pdir/f'{MODEL_NAME}_test_predictions.csv';
 import pandas as pd; pd.DataFrame({'observed_at':te.observed_at.astype(str),'customer_id':te.customer_id,'actual':te[TARGET].to_numpy(),'prediction':pred}).to_csv(predcsv,index=False)
 charts=plot_regression(out_dir,MODEL_NAME,te[TARGET].to_numpy(),pred); imp=feature_importance(pipe,FEATURES); fi=plot_importance(out_dir,MODEL_NAME,imp)
 return {'model':MODEL_NAME,'objective':OBJECTIVE,'algorithm_rationale':ALGORITHM_RATIONALE,'task':TASK,'target':TARGET,'features':FEATURES,'selected_algorithm':selected,'candidate_validation':comparison,'test_metrics':metrics,'rows':{'train':len(tr),'validation':len(va),'test':len(te)},'split':split,'artifact':str(job),'sha256':sha256(job),'predictions':str(predcsv),'charts':{**charts,'feature_importance':fi},'feature_importance':imp.to_dict('records') if imp is not None else []}
if __name__=='__main__':
 a=argparse.ArgumentParser(); a.add_argument('--out',required=True); x=a.parse_args(); print(json.dumps(run(Path(x.out)),ensure_ascii=False,indent=2,default=str))
