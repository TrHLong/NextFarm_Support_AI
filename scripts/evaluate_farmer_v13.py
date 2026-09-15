"""Export repeatable authored questions and fixture answers, without live API access."""
import argparse,csv,hashlib,importlib.util,json,sys
from pathlib import Path
from datetime import datetime,timezone
import pytest

def evaluate(project,output,baseline):
    project=Path(project).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('farmer_cases',project/'tests_device/test_farmer_acceptance.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cases=[];golden=[]
    for case in module.BANK:
        with pytest.MonkeyPatch.context() as mp:
            ask,*_=module.farmer_chat.__wrapped__(mp);response=ask(case['question']);body=response.json()
            cases.append({**case,'passed':response.status_code==200 and case['expected_tool'] in body.get('intent',[]),
              'http_status':response.status_code,'actual_tools':body.get('intent'),'answer':body.get('answer'),'trace':body.get('trace')})
    params=next(mark for mark in module.test_exact_grounded_business_facts.pytestmark if mark.name=='parametrize').args[1]
    for question,path,expected in params:
        with pytest.MonkeyPatch.context() as mp:
            ask,*_=module.farmer_chat.__wrapped__(mp);response=ask(question);actual=module.facts(response,path[0])
            for key in path[1:]:actual=actual[key]
            golden.append({'question':question,'fact_path':path,'expected':expected,'actual':actual,'passed':actual==expected,'answer':response.json()['answer']})
    old=json.loads(Path(baseline).read_text(encoding='utf-8'))
    report={'created_at':datetime.now(timezone.utc).isoformat(),'scope':'authored_development_regression_bank; synthetic HTTP fixtures, not live or field test',
      'priority_basis':'Farmer persona hypothesis; no measured user-frequency ranking',
      'fixture_clock':module.NOW.isoformat(),'bank_sha256':hashlib.sha256((project/'benchmarks/farmer-v13/questions.csv').read_bytes()).hexdigest(),
      'baseline_routing_pass':sum(r['pass'] for r in old),'routing_pass':sum(r['passed'] for r in cases),'routing_total':len(cases),
      'golden_facts_pass':sum(r['passed'] for r in golden),'golden_facts_total':len(golden),'cases':cases,'golden_facts':golden}
    (output/'question_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with (output/'question_answers.csv').open('w',encoding='utf-8-sig',newline='') as file:
        columns=['id','priority','question','expected_tool','actual_tools','passed','answer','trace']
        writer=csv.DictWriter(file,fieldnames=columns);writer.writeheader()
        for c in cases:writer.writerow({k:json.dumps(c[k],ensure_ascii=False) if isinstance(c[k],(list,dict)) else c[k] for k in columns})
    print(json.dumps({k:v for k,v in report.items() if k not in ['cases','golden_facts']}))
    return report

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--output',required=True);p.add_argument('--baseline',required=True);args=p.parse_args();evaluate(args.project,args.output,args.baseline)
