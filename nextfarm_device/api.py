import os,json,hashlib,threading,time,logging
from pathlib import Path
from datetime import datetime,timezone,timedelta
from math import isfinite
from contextlib import asynccontextmanager
from fastapi import FastAPI,Header,HTTPException,Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel,Field
from psycopg.types.json import Jsonb
import httpx
from . import VERSION as PACKAGE_VERSION
from .contracts import GROUPS,catalog,ACTIVE_SPECS,METRICS,FORECAST_HORIZONS_BY_METRIC,FORECAST_TIERS
from . import store
from .answers import route,render_tool,connectivity,norm
from .verified_answers import answer as verified_answer

MODELS=Path(os.getenv('MODEL_ARTIFACT_DIR','/models'))/'device-v11'
TOOL_GROUP={'sensor':'sensor_readings','sensor_quality':'sensor_readings','sensor_history':'sensor_readings','device_metrics':'device_status','connection':'device_status','operation':'device_status',
 'schedules':'irrigation_schedules','irrigation':'irrigation_runs','commands':'control_commands','alerts':'alerts','profile':'device_profile'}

def _horizon_label(minutes):
    minutes=int(minutes)
    if minutes%1440==0:return f'{minutes//1440} ngày'
    if minutes%60==0:return f'{minutes//60} giờ'
    return f'{minutes} phút'

def _vi_stamp(value):
    try:
        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M %d/%m/%Y')
    except (TypeError,ValueError):return str(value or 'không rõ thời điểm')

def _current_sensor_baseline(items,metrics):
    result={}
    for metric in metrics:
        valid=[]
        for row in items:
            try:value=float(row.get(metric))
            except (TypeError,ValueError):continue
            if not isfinite(value) or row.get('quality') in ['bad','suspect'] or not row.get('observed_at'):continue
            valid.append((str(row['observed_at']),value,row))
        if not valid:continue
        observed_at,value,row=max(valid,key=lambda item:item[0])
        label,unit=METRICS.get(metric,(metric,''))
        result[metric]={'label':label,'unit':unit,'value':value,'observed_at':observed_at,'zone_id':row.get('zone_id')}
    return result

def app_base(name):
    @asynccontextmanager
    async def lifespan(app):
        store.initialize_schema()
        stop=threading.Event();worker=None
        if name=='Device ML' and os.getenv('DEVICE_AUTO_TRAIN','true').lower()=='true':
            from .collection_worker import start_worker
            worker=start_worker(MODELS,stop)
        yield
        stop.set()
        if worker:worker.join(timeout=5)
    app=FastAPI(title='NextFarm '+name,version=PACKAGE_VERSION,lifespan=lifespan)
    @app.get('/health')
    def health():
        with store.connect() as db:db.execute('SELECT 1')
        return {'status':'ok','version':PACKAGE_VERSION,'service':name,'scope':'one_device','ticket_workflow':False,'collection_contract':'problem_b_v12','chat_contract':'farmer_v13'}
    return app

def data_app():
    app=app_base('Device Data')
    @app.get('/devices')
    def devices(authorization:str|None=Header(default=None)):
        user=store.user_context(authorization)
        with store.connect() as db:items=db.execute('SELECT * FROM device_db.cabinets WHERE farm_id=ANY(%s) ORDER BY device_id',(store.allowed_farms(user),)).fetchall()
        return {'items':items,'user':{'role':user['role'],'display_name':user['display_name']}}
    @app.get('/devices/{device_id}/data')
    def data(device_id:str,group:str,period:str='today',authorization:str|None=Header(default=None),zone_id:str|None=Query(default=None,max_length=80)):
        user=store.user_context(authorization);cabinet=store.authorize_device(user,device_id)
        if group=='technical_logs' and user['role']!='technician':raise HTTPException(403,'Nhật ký kỹ thuật dành cho người quản trị tri thức')
        rows=store.read_group(device_id,group,period,zone_id=zone_id)
        with store.connect() as db:db.execute('INSERT INTO device_db.read_audits(user_id,device_id,group_name) VALUES (%s,%s,%s)',(user['user_id'],device_id,group))
        return {'device_id':device_id,'customer_id':cabinet['customer_id'],'farm_id':cabinet['farm_id'],
          'group':group,'period':period,'zone_id':zone_id,'items':rows,'count':len(rows),'source':cabinet['data_origin']}
    @app.get('/devices/{device_id}/export.csv')
    def export(device_id:str,group:str,period:str='today',authorization:str|None=Header(default=None)):
        import csv,io
        result=data(device_id,group,period,authorization,zone_id=None);items=result['items'];out=io.StringIO()
        keys=list(dict.fromkeys(['customer_id','device_id','observed_at','received_at']+[k for row in items for k in row]))
        writer=csv.DictWriter(out,fieldnames=keys);writer.writeheader()
        for row in items:writer.writerow({k:json.dumps(v,ensure_ascii=False,default=str) if isinstance(v,(dict,list)) else v for k,v in {**row,'customer_id':result['customer_id'],'device_id':device_id}.items()})
        return Response(out.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="{device_id}_{group}.csv"'})
    return app

class ChatRequest(BaseModel):
    device_id:str=Field(min_length=1,max_length=100)
    zone_id:str|None=Field(default=None,min_length=1,max_length=100)
    message:str=Field(min_length=1,max_length=3000)

def chat_app():
    app=app_base('Device Chat')
    @app.post('/chat')
    def chat(payload:ChatRequest,authorization:str|None=Header(default=None)):
        user=store.user_context(authorization)
        if user['role']!='farmer':raise HTTPException(403,'Kỹ thuật viên chỉ duyệt tri thức và xem dữ liệu; không trực chat')
        cabinet=store.authorize_device(user,payload.device_id);profile={**cabinet['profile'],**{k:cabinet[k] for k in ['device_name','device_id']}}
        plan=route(payload.message);evidence=[];answers=[];results=[]
        # The zone selected in the farmer UI scopes natural questions that do not repeat a zone name.
        configured_zones=[z.get('zone_id') for z in profile.get('zones',[]) if z.get('zone_id')]
        if payload.zone_id and payload.zone_id not in configured_zones:
            raise HTTPException(422,'Khu đã chọn không tồn tại trong hồ sơ vườn.')
        default_zone=payload.zone_id or (configured_zones[0] if len(configured_zones)==1 else None)
        if default_zone:
            zone_tools={'sensor','sensor_history','sensor_quality','irrigation','schedules','alerts','overview','models'}
            for task in plan.get('requests',[]):
                if task.get('tool') in zone_tools and not task.get('zone_id'):task['zone_id']=default_zone
            if not plan.get('zone_id'):plan['zone_id']=default_zone
        # User-supplied alternate ID cannot override the selected cabinet.
        if any(other in payload.message for other in ['cabinet_long','cabinet_lan','cabinet_minh'] if other!=payload.device_id):
            answers=['Cuộc chat đang gắn với vườn đang xem. Hãy chọn vườn khác trước khi hỏi dữ liệu của vườn đó.'];plan['tools']=[];plan['requests']=[]
        with httpx.Client(timeout=20,headers={'Authorization':authorization}) as client:
            base=os.getenv('FARM_DATA_URL','http://farm-data-service:8000')
            fetch_cache={}
            def fetch(group,period='today',task=None):
                params={'group':group,'period':period}
                task=task or {}
                if task.get('zone_id') and group in ['sensor_readings','irrigation_schedules','irrigation_runs','alerts']:params['zone_id']=task['zone_id']
                key=(group,period,params.get('zone_id'))
                if key in fetch_cache:return dict(fetch_cache[key])
                r=client.get(f'{base}/devices/{payload.device_id}/data',params=params);r.raise_for_status();value=r.json()
                if value.get('device_id')!=payload.device_id or value.get('customer_id')!=cabinet['customer_id']:raise HTTPException(502,'Bằng chứng sai phạm vi khách hàng/tủ')
                for row in value.get('items',[]):
                    if row.get('device_id',payload.device_id)!=payload.device_id or row.get('customer_id',cabinet['customer_id'])!=cabinet['customer_id']:raise HTTPException(502,'Bản ghi sai phạm vi khách hàng/tủ')
                evidence.append(value);fetch_cache[key]=dict(value);return value
            for task in plan.get('requests',[]):
                tool=task['tool']
                try:
                    if tool=='out_of_scope':
                        if task.get('scope_kind')=='garden_data_missing':
                            text='Câu hỏi này có liên quan đến vườn nhưng nằm ngoài phạm vi dữ liệu thiết bị hiện có. Cơ sở dữ liệu chưa có đủ thông tin để giải đáp nên tôi sẽ không suy đoán. Tôi có thể hỗ trợ số đo cảm biến, trạng thái thiết bị, lịch tưới, lịch sử tưới, nhật ký lệnh và cảnh báo.'
                        else:
                            text='Câu hỏi này nằm ngoài phạm vi dữ liệu thiết bị vườn. Hiện tôi chưa có dữ liệu để trả lời. Tôi hỗ trợ số đo cảm biến, trạng thái thiết bị, lịch tưới, lịch sử tưới, nhật ký lệnh và cảnh báo.'
                        value={'text':text,'facts':{},'status':'out_of_scope'}
                        answers.append(value['text']);results.append({'request':task,**value});continue
                    if tool=='clarify':
                        value={'text':task.get('reason','Hãy cho biết nhóm dữ liệu, khu và khoảng thời gian bạn muốn hỏi.'),'facts':{},'status':'needs_clarification'}
                        answers.append(value['text']);results.append({'request':task,**value});continue
                    if tool=='read_only_policy':answers.append('Chat chỉ đọc và giải thích dữ liệu. Muốn điều khiển hãy dùng màn hình điều khiển tủ và các khóa an toàn tại bo.');continue
                    if tool=='identity':answers.append('Chat đang dùng bộ định tuyến quy tắc và công cụ đọc dữ liệu. Không gọi OpenAI hay Gemini. Các model dự báo riêng chỉ dùng khi vượt kiểm định trong phạm vi đã công bố.');continue
                    if tool=='provenance':
                        answers.append(f'Cuộc chat chỉ đọc tủ {payload.device_id} của khách hàng {cabinet["customer_id"]}, sau khi xác thực quyền tài khoản. Mốc ngày/tuần/tháng dùng múi giờ UTC+7. Số liệu lấy qua API theo tủ; bản ghi bằng chứng nằm trong trace của câu trả lời. Tab Dữ liệu xuất CSV có customer_id và device_id. Câu hỏi và phản hồi không tự động trở thành dữ liệu train.');continue
                    if tool=='models':
                        requested=task.get('model_names',[])
                        requested_metrics=task.get('metrics',[])
                        horizons=task.get('requested_horizons') or [task.get('horizon_minutes',360)]
                        prediction_params={'metrics':','.join(requested_metrics),'horizons':','.join(str(value) for value in horizons)}
                        r=client.get(os.getenv('ANALYTICS_URL','http://ai-analytics-service:8000')+f'/devices/{payload.device_id}/predict',params=prediction_params);r.raise_for_status();result=r.json();evidence.append(result)
                        predictions=result.get('predictions',[])
                        if result.get('device_id')!=payload.device_id:raise HTTPException(502,'Dự báo sai phạm vi tủ')
                        if requested:
                            predictions=[p for p in predictions if p.get('model') in requested and p.get('horizon_minutes') in horizons]
                        baseline={}
                        if requested_metrics:
                            baseline_period='latest_all' if len(profile.get('zones',[]))>1 and not task.get('zone_id') else 'latest'
                            baseline=_current_sensor_baseline(fetch('sensor_readings',baseline_period,task).get('items',[]),requested_metrics)
                        horizon_text=', '.join(_horizon_label(value) for value in horizons)
                        metric_text=', '.join(METRICS.get(metric,(metric,''))[0] for metric in requested_metrics) or 'chỉ số được hỏi'
                        if predictions:
                            forecast_parts=[]
                            for prediction in predictions:
                                unit=METRICS.get(prediction.get('metric'),('',prediction.get('unit','')))[1] or prediction.get('unit','')
                                target_at=''
                                try:
                                    observed=datetime.fromisoformat(str(prediction.get('observed_at')).replace('Z','+00:00'))
                                    target_at='; mốc dự báo '+_vi_stamp(observed+timedelta(minutes=int(prediction['horizon_minutes'])))
                                except (TypeError,ValueError,KeyError):pass
                                forecast_parts.append(f'{prediction.get("title",prediction.get("model","Dự báo"))}: {float(prediction["value"]):.2f} {unit}{target_at}')
                            text='Dự báo đã vượt kiểm định cho đúng mốc được hỏi: '+'; '.join(forecast_parts)+'. Kết quả có sai số và cần đối chiếu số đo mới khi đến gần thời điểm hành động.'
                            status='answered'
                        else:
                            text=f'Chưa thể phát hành dự báo {horizon_text} cho {metric_text}: chưa có model đúng mốc thời gian đã vượt kiểm định trên dữ liệu vận hành đủ dài. Tôi không dùng biểu đồ 2 giờ hoặc số đo hiện tại để giả làm dự báo.'
                            if baseline:
                                stamps=sorted({value['observed_at'] for value in baseline.values()})
                                values='; '.join(f'{value["label"]} {value["value"]:.2f} {value["unit"]}'.strip() for value in baseline.values())
                                text+=f' Điểm xuất phát thực đo lúc {_vi_stamp(stamps[-1])}: {values}. Đây là số đo hiện tại, không phải giá trị tương lai.'
                            status='forecast_unavailable'
                        answers.append(text)
                        policy={metric:FORECAST_HORIZONS_BY_METRIC.get(metric,[]) for metric in requested_metrics}
                        results.append({'request':task,'status':status,'facts':{'predictions':predictions,'current_baseline':baseline,
                          'requested_horizons':horizons,'recommended_horizons':policy,'forecast_tiers':FORECAST_TIERS}})
                        continue
                    if tool=='knowledge':
                        from .knowledge import retrieve
                        know=retrieve(task.get('question',payload.message))
                        if know.get('answerable'):
                            answers.append(know['answer']+'\nNguồn: '+know['source']['title']+' / '+str(know['source']['section'])+'; mã đoạn '+know['source']['chunk_id']);evidence.append(know);continue
                        answers.append('Chưa có dữ liệu hoặc hướng dẫn đã duyệt phù hợp. Hãy cho biết chỉ số, tên ngõ ra và khoảng thời gian. Trợ lý hỗ trợ dữ liệu thiết bị, tưới và châm phân của tủ đang chọn.');continue
                    if tool=='overview':
                        tool_period=task.get('period','today')
                        sensor_period='latest_all' if len(profile.get('zones',[]))>1 and not task.get('zone_id') else 'latest'
                        overview_data={
                          'sensor':fetch('sensor_readings',sensor_period,task),
                          'status':fetch('device_status','latest',task),
                          'irrigation':fetch('irrigation_runs',tool_period,task),
                          # Device-level alerts may not carry a zone; fetch them and filter safely in the overview renderer.
                          'alerts':fetch('alerts',tool_period,{**task,'zone_id':None})}
                        value=verified_answer('overview',overview_data,task,task.get('question',payload.message),profile)
                        answers.append(value['text']);results.append({'request':task,**value});continue
                    tool_period=task.get('period','today')
                    period='latest' if tool in ['sensor','sensor_quality','device_metrics'] or (task.get('operation')=='last' and not task.get('period_explicit') and tool in ['irrigation','commands','alerts']) else tool_period
                    if tool in ['sensor','sensor_quality'] and not task.get('zone_id') and len(profile.get('zones',[]))>1:period='latest_all'
                    if task.get('operation')=='compare_zones':period='latest_all'
                    result=fetch(TOOL_GROUP[tool],period,task)
                    observer=None
                    if tool in ['connection','operation']:observer=next(iter(fetch('connection_observer')['items']),{})
                    if tool in ['irrigation','sensor_history'] and task.get('operation')=='compare':
                        previous={'today':'yesterday','week':'last_week','month':'last_month'}.get(tool_period,'yesterday')
                        result['previous_items']=fetch(TOOL_GROUP[tool],previous,task)['items']
                    value=verified_answer(tool,result,task,task.get('question',payload.message),profile,observer)
                    answers.append(value['text']);results.append({'request':task,**value})
                except httpx.HTTPStatusError as exc:
                    value={'text':'Chưa thể xác minh dữ liệu trong phạm vi được hỏi. Nếu khoảng thời gian quá dài, hãy chọn kỳ ngắn hơn.','facts':{},'status':'data_unavailable'}
                    answers.append(value['text']);results.append({'request':task,**value})
                except httpx.HTTPError:
                    answers.append('Dịch vụ dữ liệu chưa sẵn sàng. Tôi chưa thể kiểm chứng số liệu cho phần câu hỏi này; hãy thử lại sau.')
                    results.append({'request':task,'status':'data_unavailable','facts':{}})
        # Defensive de-duplication: one natural sentence can contain two
        # phrasings of the same intent, but the farmer should see one answer.
        answers=list(dict.fromkeys(text.strip() for text in answers if text and text.strip()))
        farm_name=profile.get('farm_name') or (('Vườn '+str(profile.get('crop'))) if profile.get('crop') else 'Vườn của bạn')
        answer='Vườn đang xem: '+farm_name+'.\n\n'+'\n\n'.join(answers)
        # Provenance remains structured in `source` and in the persistent demo
        # notice in the UI; do not repeat the same source footer on every turn.
        # All numerical answers above are templates built from scoped evidence; no free-form external LLM.
        trace={'plan':plan,'evidence':evidence,'device_id':payload.device_id,'scope_verified':True,
           'response_method':'evidence_templates','training_use_allowed':False,'ticket_created':False,'results':results}
        with store.connect() as db:
            row=db.execute('INSERT INTO device_db.chat_log(user_id,device_id,question,answer,trace) VALUES (%s,%s,%s,%s,%s) RETURNING id',(user['user_id'],payload.device_id,payload.message,answer,Jsonb(trace))).fetchone()
        return {'answer':answer,'device_id':payload.device_id,'intent':plan['tools'],'trace':trace,'chat_id':row['id'],'source':cabinet['data_origin']}
    @app.get('/conversations/current/messages')
    def history(device_id:str,authorization:str|None=Header(default=None)):
        user=store.user_context(authorization);store.authorize_device(user,device_id)
        with store.connect() as db:rows=db.execute('SELECT id,question,answer,created_at FROM device_db.chat_log WHERE user_id=%s AND device_id=%s ORDER BY id DESC LIMIT 40',(user['user_id'],device_id)).fetchall()
        return {'items':list(reversed(rows))}
    class Feedback(BaseModel):
        chat_id:int; useful:bool; comment:str=Field(default='',max_length=2000)
    @app.post('/feedback')
    def feedback(payload:Feedback,authorization:str|None=Header(default=None)):
        user=store.user_context(authorization)
        with store.connect() as db:
            row=db.execute('SELECT * FROM device_db.chat_log WHERE id=%s AND user_id=%s',(payload.chat_id,user['user_id'])).fetchone()
            if not row:raise HTTPException(403,'Không có quyền đánh giá cuộc chat')
            db.execute('INSERT INTO device_db.chat_feedback(chat_id,user_id,useful,comment) VALUES (%s,%s,%s,%s)',(payload.chat_id,user['user_id'],payload.useful,payload.comment))
        return {'saved':True,'training_use_allowed':False}
    @app.post('/tickets/confirm')
    def retired():raise HTTPException(410,'Luồng ticket đã ngừng sử dụng')
    return app

def model_reports():
    path=MODELS.parent/'problem-b/latest_training_report.json'
    state=MODELS.parent/'problem-b/collection_state.json'
    collection=json.loads(state.read_text(encoding='utf-8')) if state.exists() else {'status':'NOT_STARTED','devices':{}}
    result=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'models':[{'name':s.name,'title':s.title,'status':'WAITING_DATA','gate_reasons':['Chờ dữ liệu thu đủ 72 giờ; bộ mô phỏng v11 không dùng làm kết quả bài toán B']} for s in ACTIVE_SPECS],'ready_count':0,'production_ready':False,'train_executed':False}
    result['collection']=collection
    result['historical_experiment']='Bộ model v11 là thí nghiệm lịch sử, chưa chứng minh trên CSV vận hành theo hợp đồng 72 giờ'
    return result

def analytics_app():
    app=app_base('Device ML')
    @app.get('/devices/{device_id}/predict')
    def inference(device_id:str,authorization:str|None=Header(default=None),metrics:str|None=Query(default=None,max_length=300),horizons:str|None=Query(default=None,max_length=120)):
        user=store.user_context(authorization);cab=store.authorize_device(user,device_id)
        # No synthetic-only registry may serve as proof of runtime/customer validation.
        requested_metrics=[value for value in (metrics or '').split(',') if value]
        requested_horizons=[int(value) for value in (horizons or '').split(',') if value.isdigit()]
        return {'device_id':device_id,'predictions':[],'status':'NOT_VALIDATED',
          'reason':'Chưa có model đúng mốc dự báo được nghiệm thu trên dữ liệu vận hành đủ dài và kiểm định độc lập. Số đo hiện tại vẫn được đọc trực tiếp từ API gốc.',
          'requested_metrics':requested_metrics,'requested_horizons':requested_horizons,
          'recommended_horizons':{metric:FORECAST_HORIZONS_BY_METRIC.get(metric,[]) for metric in requested_metrics},
          'forecast_tiers':FORECAST_TIERS,'production_ready':False}
    @app.get('/devices/{device_id}/models')
    def reports(device_id:str,authorization:str|None=Header(default=None)):
        user=store.user_context(authorization);store.authorize_device(user,device_id)
        result=model_reports()
        if 'devices' in result['collection']:result['collection']['devices']={device_id:result['collection']['devices'].get(device_id,{})}
        # Do not expose other customer rows or file identities to farmers.
        if user['role']=='farmer':
            return {'device_id':device_id,'production_ready':False,'status':'NOT_VALIDATED',
              'forecast_focus':{metric:horizons for metric,horizons in FORECAST_HORIZONS_BY_METRIC.items() if metric in ['temperature','air_humidity','soil_moisture','ec','ph']},
              'note':'Chưa phát hành model dự báo cho nông dân khi chưa qua kiểm định dữ liệu vận hành. Sản phẩm chỉ hiển thị năm mục tiêu dự báo canh tác cốt lõi, không quảng bá số lượng model thử nghiệm.'}
        return result
    @app.get('/automation')
    def automation(authorization:str|None=Header(default=None)):
        user=store.user_context(authorization)
        if user['role']!='technician':raise HTTPException(403,'Chỉ quản trị tri thức được xem vận hành ML')
        p=MODELS.parent/'problem-b/collection_state.json'
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'status':'WAITING'}
    return app

def catalog_app():
    app=app_base('Device Capabilities')
    @app.get('/devices/{device_id}/capabilities')
    def capabilities(device_id:str,authorization:str|None=Header(default=None)):
        user=store.user_context(authorization);store.authorize_device(user,device_id)
        with store.connect() as db:groups=[r['group_name'] for r in db.execute('SELECT DISTINCT group_name FROM device_db.events WHERE device_id=%s',(device_id,)).fetchall()]
        items=[x for x in catalog({},groups+['device_profile']) if x['kind']=='rule_or_query']
        return {'device_id':device_id,'items':items,'total':len(items),'production_ready':False,
                'note':'Sáu nhóm dữ liệu cốt lõi của nông dân. Các phép tính chi tiết là thao tác nội bộ, không được quảng bá thành AI hay năng lực riêng.'}
    return app

def gateway_app():
    app=app_base('Device Router')
    @app.post('/plan')
    def plan(payload:ChatRequest,x_internal_service_key:str|None=Header(default=None)):
        import hmac
        key=os.getenv('INTERNAL_SERVICE_KEY','')
        if not key or not hmac.compare_digest(x_internal_service_key or '',key):raise HTTPException(401,'Yêu cầu nội bộ chưa xác thực')
        return {**route(payload.message),'device_id':payload.device_id,'provider':'deterministic','active_external_llm':False}
    return app
