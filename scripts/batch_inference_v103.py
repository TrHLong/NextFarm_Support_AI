import argparse,json,joblib
from pathlib import Path
import pandas as pd

def main():
 p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--model-dir',default='model-artifacts/simulation-v104/latest/models');a=p.parse_args()
 art=joblib.load(Path(a.model_dir)/(a.model+'.joblib'));df=pd.read_csv(a.input);missing=[c for c in art['features'] if c not in df]
 if missing:raise SystemExit('Thiếu feature: '+','.join(missing))
 pred=art['pipeline'].predict(df[art['features']]);out=df.copy();out['prediction']=pred
 if art['task']=='classification' and hasattr(art['pipeline'],'predict_proba'):
  probs=art['pipeline'].predict_proba(df[art['features']]);
  for i,c in enumerate(art['pipeline'].classes_):out[f'probability_{c}']=probs[:,i]
 out.to_csv(a.output,index=False);print(json.dumps({'rows':len(out),'output':a.output,'scope':art['scope']}))
if __name__=='__main__':main()
