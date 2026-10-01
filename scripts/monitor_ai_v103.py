import argparse,json
from pathlib import Path
import pandas as pd
p=argparse.ArgumentParser();p.add_argument('--log-dir',default='logs/ai-inference');p.add_argument('--out',default='model-artifacts/simulation-v104/monitoring_summary.json');a=p.parse_args()
rows=[]
for f in Path(a.log_dir).glob('inference-*.jsonl'):
 for line in f.read_text(encoding='utf-8').splitlines():
  try:rows.append(json.loads(line))
  except:pass
if not rows: summary={'records':0,'note':'Chưa có inference log'}
else:
 d=pd.DataFrame(rows);summary={'records':len(d),'by_model':{}}
 for m,g in d.groupby('model'):
  summary['by_model'][m]={'requests':len(g),'latency_ms_mean':float(g.latency_ms.mean()),'latency_ms_p95':float(g.latency_ms.quantile(.95)),'exposed_fraction':float(g.exposed.mean())}
Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
