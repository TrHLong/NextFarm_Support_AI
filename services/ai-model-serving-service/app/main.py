from __future__ import annotations
import os, json, time, hashlib
from pathlib import Path
from datetime import datetime, timezone
import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

PROJECT=Path(os.getenv('NEXTFARM_PROJECT_ROOT',Path(__file__).resolve().parents[3]))
ARTIFACT_DIR=Path(os.getenv('NEXTFARM_MODEL_DIR',PROJECT/'model-artifacts/simulation-v104/latest/models'))
LOG_DIR=Path(os.getenv('NEXTFARM_INFERENCE_LOG_DIR',PROJECT/'logs/ai-inference')); LOG_DIR.mkdir(parents=True,exist_ok=True)
MODE=os.getenv('NEXTFARM_AI_MODE','shadow').lower()  # shadow | ab10 | simulation

class PredictRequest(BaseModel):
    entity_id:str=Field(...,description='farm/zone/device stable id')
    features:dict[str,float|int|bool|None]

app=FastAPI(title='NextFarm AI Model Serving',version='10.4-simulation')
_cache={}

def _artifact(name):
    if name not in _cache:
        p=ARTIFACT_DIR/f'{name}.joblib'
        if not p.exists(): raise HTTPException(404,f'Không tìm thấy model {name}')
        obj=joblib.load(p)
        if obj.get('scope')!='SYNTHETIC_SIMULATION_ONLY': raise HTTPException(503,'Artifact scope không hợp lệ cho service mô phỏng')
        _cache[name]=obj
    return _cache[name]

def _ab_enabled(entity_id:str)->bool:
    bucket=int(hashlib.sha256(entity_id.encode()).hexdigest()[:8],16)%100
    return bucket<10

def _log(rec):
    day=datetime.now(timezone.utc).strftime('%Y%m%d')
    with (LOG_DIR/f'inference-{day}.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(rec,ensure_ascii=False,default=str)+'\n')

@app.get('/health')
def health():
    return {'status':'ok','mode':MODE,'scope':'SYNTHETIC_SIMULATION_ONLY','artifact_dir':str(ARTIFACT_DIR)}

@app.get('/models')
def models():
    out=[]
    for p in sorted(ARTIFACT_DIR.glob('*.joblib')):
        a=_artifact(p.stem); out.append({'name':p.stem,'task':a['task'],'status':a['status'],'scope':a['scope'],'features':a['features']})
    return {'models':out}

@app.post('/predict/{model_name}')
def predict(model_name:str, req:PredictRequest):
    a=_artifact(model_name); missing=[x for x in a['features'] if x not in req.features]
    if missing: raise HTTPException(422,{'message':'Thiếu feature','missing':missing})
    t=time.perf_counter(); X=pd.DataFrame([{c:req.features.get(c) for c in a['features']}]); pipe=a['pipeline']; raw=pipe.predict(X)[0]
    if a['task']=='classification':
        pred=int(raw); result={'class':pred}
        if hasattr(pipe,'predict_proba'):
            probs=pipe.predict_proba(X)[0]; result['probabilities']={str(c):float(v) for c,v in zip(pipe.classes_,probs)}
        if a.get('label_mapping'): result['label']=a['label_mapping'].get(str(pred),str(pred))
    else: result={'value':float(raw)}
    latency=(time.perf_counter()-t)*1000
    exposed=(MODE=='simulation') or (MODE=='ab10' and _ab_enabled(req.entity_id))
    # shadow: always compute/log but caller receives only metadata, never an actionable recommendation.
    rec={'timestamp':datetime.now(timezone.utc).isoformat(),'model':model_name,'entity_id':req.entity_id,'mode':MODE,'exposed':exposed,'latency_ms':latency,'result':result}
    _log(rec)
    return {'model':model_name,'mode':MODE,'scope':a['scope'],'exposed':exposed,'prediction':result if exposed else None,'shadow_logged':True,'latency_ms':round(latency,3)}
