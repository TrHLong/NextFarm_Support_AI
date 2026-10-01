from __future__ import annotations
import argparse,json
from pathlib import Path
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor, HistGradientBoostingRegressor
from common import *
MODEL_NAME='smart_irrigation_scheduler'; TASK='regression'; TARGET='target_irrigation_minutes'; FEATURES=BASE
OBJECTIVE='Ước lượng số phút tưới đề xuất theo policy mô phỏng từ thiếu hụt độ ẩm, nhiệt độ, độ ẩm không khí và lịch sử cảm biến.'
ALGORITHM_RATIONALE=('Bài toán là hồi quy phi tuyến dạng bảng; Extra Trees và Random Forest được benchmark vì học tốt ngưỡng và tương tác mà không cần scaling, '
'MAE Validation là tiêu chí chọn vì đơn vị phút dễ diễn giải trực tiếp. Kết quả cực cao phải được hiểu là khả năng học policy simulator, không phải chứng minh tối ưu tưới ngoài thực địa.')

def run(out_dir:Path):
 raw=load_raw(); df=build_features(raw); tr,va,te,split=temporal_customer_split(df)
 candidates=[('ExtraTreesRegressor',ExtraTreesRegressor(n_estimators=60,min_samples_leaf=3,max_features=.85,n_jobs=-1,random_state=SEED)),('RandomForestRegressor',RandomForestRegressor(n_estimators=60,min_samples_leaf=3,max_features=.85,n_jobs=-1,random_state=SEED))]
 (selected,pipe),comparison=select_candidate(TASK,candidates,tr,va,FEATURES,TARGET); pred=pipe.predict(te[FEATURES]); metrics=regression_metrics(te[TARGET],pred); job,_=save_model_artifact(out_dir,MODEL_NAME,pipe,FEATURES,TARGET,TASK)
 import pandas as pd; pdir=out_dir/'predictions'; pdir.mkdir(parents=True,exist_ok=True); predcsv=pdir/f'{MODEL_NAME}_test_predictions.csv'; pd.DataFrame({'observed_at':te.observed_at.astype(str),'customer_id':te.customer_id,'actual':te[TARGET].to_numpy(),'prediction':pred}).to_csv(predcsv,index=False)
 charts=plot_regression(out_dir,MODEL_NAME,te[TARGET].to_numpy(),pred); imp=feature_importance(pipe,FEATURES); fi=plot_importance(out_dir,MODEL_NAME,imp)
 return {'model':MODEL_NAME,'objective':OBJECTIVE,'algorithm_rationale':ALGORITHM_RATIONALE,'task':TASK,'target':TARGET,'features':FEATURES,'selected_algorithm':selected,'candidate_validation':comparison,'test_metrics':metrics,'rows':{'train':len(tr),'validation':len(va),'test':len(te)},'split':split,'artifact':str(job),'sha256':sha256(job),'predictions':str(predcsv),'charts':{**charts,'feature_importance':fi},'feature_importance':imp.to_dict('records') if imp is not None else []}
if __name__=='__main__':
 a=argparse.ArgumentParser(); a.add_argument('--out',required=True); x=a.parse_args(); print(json.dumps(run(Path(x.out)),ensure_ascii=False,indent=2,default=str))
