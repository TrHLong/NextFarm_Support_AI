"""HTTP acceptance checks. Credentials loaded from .env, never written to results."""
import argparse,json,os,time,sys
from pathlib import Path
from datetime import datetime,timezone
import httpx

def main():
    p=argparse.ArgumentParser();p.add_argument('--base',default='http://127.0.0.1:19080');p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--output',type=Path,default=Path('device_acceptance.json'));p.add_argument('--scenarios',action='store_true');p.add_argument('--simulator',default='http://127.0.0.1:18400')
    a=p.parse_args();env={}
    for line in (a.project_root/'.env').read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1);env[k.strip()]=v.strip().strip('"').strip("'")
    results=[]
    def check(name,ok,**details):
        results.append({'case':name,'passed':bool(ok),**details});print(('PASS ' if ok else 'FAIL ')+name,flush=True)
    with httpx.Client(base_url=a.base,timeout=90) as c:
        tokens={}
        for who in ['long','lan','minh','tech']:
            r=c.post('/api/identity/auth/login',json={'username':'kythuat.01' if who=='tech' else 'nongdan.'+who,'password':env['NEXTFARM_TECH_PASSWORD' if who=='tech' else 'NEXTFARM_FARMER_PASSWORD']})
            check('login_'+who,r.status_code==200,status=r.status_code)
            if r.status_code!=200:continue
            tokens[who]={'Authorization':'Bearer '+r.json()['access_token']}
            d=c.get('/api/farm/devices',headers=tokens[who]);items=d.json().get('items',[])
            check('device_scope_'+who,len(items)==(3 if who=='tech' else 1) and (who=='tech' or all(x['device_id']=='cabinet_'+who for x in items)),devices=[x['device_id'] for x in items])
            if who=='tech':continue
            for group in ['sensor_readings','device_status','irrigation_schedules','irrigation_runs','control_commands','alerts','device_profile']:
                r=c.get(f'/api/farm/devices/cabinet_{who}/data',params={'group':group,'period':'week'},headers=tokens[who]);data=r.json()
                check(who+'_'+group,r.status_code==200 and data.get('count',0)>0 and data.get('customer_id')=='customer_'+who,count=data.get('count',0))
        h=tokens['long']
        for endpoint in ['/api/farm/devices/cabinet_lan/data?group=sensor_readings','/api/farm/devices/cabinet_lan/export.csv?group=sensor_readings','/api/analytics/devices/cabinet_lan/predict','/api/router/devices/cabinet_lan/capabilities']:
            r=c.get(endpoint,headers=h);check('deny_other_customer_'+endpoint.split('/')[2]+'_'+endpoint.split('/')[-1].split('?')[0],r.status_code==403,status=r.status_code)
        r=c.post('/api/chatbot/chat',headers=h,json={'message':'Độ ẩm?'});check('require_selected_device',r.status_code==422)
        r=c.post('/api/chatbot/chat',headers=tokens['tech'],json={'device_id':'cabinet_long','message':'Độ ẩm?'});check('tech_cannot_reply_chat',r.status_code==403)
        r=c.post('/api/chatbot/tickets/confirm',headers=h,json={});check('ticket_retired',r.status_code==410)
        cases=[('soil','Độ ẩm 62% có cao không?','sensor'),('status','Bơm có đang chạy không?','operation'),('irrigation','Tuần này tưới mấy lần hết bao nhiêu nước?','irrigation'),('commands','Ai đã bật bơm hôm qua?','commands'),('no_external_llm','Đang dùng ChatGPT hay Gemini?','identity'),('unsupported_forecast','Dự báo độ ẩm không khí sau 30 phút','models'),('unknown','Giá vàng ngày mai thế nào?','knowledge'),('scope_hint','Đọc cabinet_lan giúp tôi',None)]
        for name,q,intent in cases:
            r=c.post('/api/chatbot/chat',headers=h,json={'device_id':'cabinet_long','message':q});v=r.json();answer=v.get('answer','');trace=v.get('trace',{})
            ok=r.status_code==200 and v.get('device_id')=='cabinet_long' and not trace.get('ticket_created')
            if intent:ok=ok and intent in v.get('intent',[])
            if name=='unsupported_forecast':ok=ok and 'Chưa phát hành dự báo' in answer
            if name=='unknown':ok=ok and 'Chưa có dữ liệu' in answer
            if name=='no_external_llm':ok=ok and 'Không gọi OpenAI hay Gemini' in answer
            if name=='scope_hint':ok=ok and not trace.get('evidence')
            check('chat_'+name,ok,question=q,answer=answer,status=r.status_code,intents=v.get('intent'),evidence_groups=[x.get('group') for x in trace.get('evidence',[]) if 'group' in x])
        r=c.get('/api/analytics/devices/cabinet_long/models',headers=h);m=r.json();check('ten_model_reports',r.status_code==200 and len(m.get('models',[]))==10,ready_count=m.get('ready_count'))
        r=c.get('/api/router/devices/cabinet_long/capabilities',headers=h);v=r.json();check('32_support_functions',v.get('total')==32 and all(x['kind']=='rule_or_query' for x in v.get('items',[])),ready_count=sum(x['status']=='READY' for x in v.get('items',[])))
        r=c.get('/api/analytics/devices/cabinet_long/predict',headers=h);v=r.json();check('actual_artifact_inference',r.status_code==200 and len(v.get('predictions',[]))>0,prediction_count=len(v.get('predictions',[])),reason=v.get('reason'))
        r=c.get('/api/farm/devices/cabinet_long/export.csv?group=sensor_readings&period=week',headers=h);check('csv_has_owner_and_device',r.status_code==200 and all(x in r.text.splitlines()[0] for x in ['customer_id','device_id']),bytes=len(r.content))
        if a.scenarios:
            try:
                for scenario,expected in [('power_loss','mất nguồn'),('mqtt_loss','MQTT bị gián đoạn')]:
                    r=httpx.post(a.simulator+f'/scenarios/cabinet_long/{scenario}',headers={'X-Internal-Service-Key':env['INTERNAL_SERVICE_KEY']},timeout=10);r.raise_for_status();time.sleep(6)
                    r=c.post('/api/chatbot/chat',headers=h,json={'device_id':'cabinet_long','message':'Tủ không gửi dữ liệu nữa vì sao?'});v=r.json()
                    check('scenario_'+scenario,r.status_code==200 and expected in v.get('answer',''),answer=v.get('answer'))
            finally:httpx.post(a.simulator+'/scenarios/cabinet_long/normal',headers={'X-Internal-Service-Key':env['INTERNAL_SERVICE_KEY']},timeout=10).raise_for_status()
    report={'executed_at':datetime.now(timezone.utc).isoformat(),'base':a.base,'suite':'device_v11_acceptance','passed':sum(x['passed'] for x in results),'total':len(results),'results':results,'simulation':True,'docker_build_verified':False}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if all(x['passed'] for x in results) else 1
if __name__=='__main__':sys.exit(main())
