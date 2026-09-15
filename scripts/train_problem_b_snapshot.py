"""Reproduce an immutable runtime snapshot; routine runs use collection_worker."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nextfarm_device.runtime_training import train_snapshot

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='Use a new output directory to preserve prior evidence')
    args=parser.parse_args();result=train_snapshot(args.snapshot,args.output)
    print('Status:',result['status'],'trained:',result.get('trained_count',0),'READY:',result['ready_count'])
    print('Report:',args.output/'runs'/args.snapshot.name/'training_report.html')
