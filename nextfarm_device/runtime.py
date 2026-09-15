"""Live simulator and MQTT ingestion. Raw status 5 s; sensor wire 60 s, storage 10 min."""
import json,os,threading,time,math,random,uuid,logging
from contextlib import asynccontextmanager
from datetime import datetime,timezone,timedelta
import paho.mqtt.client as mqtt
from fastapi import FastAPI,Header,HTTPException
from . import store
from .answers import connectivity
from .collection import VERSION

def mqtt_client(name):
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=name)
    if os.getenv('MQTT_USERNAME'):client.username_pw_set(os.getenv('MQTT_USERNAME'),os.getenv('MQTT_PASSWORD'))
    if os.getenv('MQTT_TLS','false').lower()=='true':client.tls_set(ca_certs=os.getenv('MQTT_CA_CERT') or None)
    client.reconnect_delay_set(1,30)
    return client

def schedule_outputs(elapsed,scheduled,power,latched):
    """Declared simulation timing, seconds from the 30-minute local schedule start.
    Open zone first; pump after 5s, fertilizer after 10s. Fertilizer stops at
    12min, water before the last 3s, zone at end. Telemetry samples every 5s.
    """
    allowed=scheduled and power and not latched
    return {'valve':bool(allowed and 0<=elapsed<1800),
            'pump':bool(allowed and 5<=elapsed<1797),
            'fertilizer':bool(allowed and 10<=elapsed<720)}


def ingestion_app():
    state={'connected':False,'received':0,'stored':0,'rejected':0,'last_error':None};client=None
    def on_message(_client,_userdata,msg):
        try:
            body=json.loads(msg.payload);device=body['device_id'];group=body['group'];stamp=body['observed_at']
            if group not in ['sensor_readings','device_status','irrigation_runs','control_commands','technical_logs']:raise ValueError('Unsupported group')
            if msg.topic!=f'nextfarm/device/{device}/{group}':raise ValueError('Topic/device mismatch')
            if body.get('source')!='synthetic_device_spec_v11':raise ValueError('Demo adapter requires explicit synthetic origin; production adapter must validate its own device credentials')
            payload=body['payload'];payload.update(source=body['source'],collection_version=VERSION,acquisition_method='mqtt_live')
            observed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            if observed.tzinfo is None or observed>datetime.now(timezone.utc)+timedelta(seconds=30):raise ValueError('Invalid timestamp')
            bucket=observed.replace(minute=observed.minute//10*10,second=0,microsecond=0)
            key=f'sensor:{bucket.isoformat()}' if group=='sensor_readings' else body['event_id']
            with store.connect() as db:
                stored=store.put_event(db,device,group,stamp,payload,key)
                state['stored']+=stored
            state['received']+=1;state['last_error']=None
        except Exception as exc:state['rejected']+=1;state['last_error']=type(exc).__name__
    @asynccontextmanager
    async def life(app):
        nonlocal client
        store.initialize_schema();client=mqtt_client('nextfarm-v11-ingest')
        def connected(c,u,f,r,p):
            state['connected']=not r.is_failure
            if state['connected']:c.subscribe('nextfarm/device/+/+',qos=1)
        client.on_connect=connected;client.on_disconnect=lambda *a:state.update(connected=False);client.on_message=on_message
        client.connect_async(os.getenv('MQTT_HOST','mosquitto'),int(os.getenv('MQTT_PORT','1883')),30);client.loop_start()
        yield
        client.disconnect();client.loop_stop()
    app=FastAPI(lifespan=life)
    @app.get('/health')
    def health():return {'status':'ok' if state['connected'] else 'waiting_mqtt','version':'12.0.0',**state}
    return app

def simulator_app():
    state={'running':False,'connected':False,'last_error':None,'published':0};stop=threading.Event();forced={}
    def worker():
        try:
            # Never manufacture three days of historical telemetry at startup.
            with store.connect() as db:devices=db.execute('SELECT * FROM device_db.cabinets ORDER BY device_id').fetchall()
            with store.connect() as db:
                for cabinet in devices:
                    for schedule in cabinet['profile'].get('schedules',[]):
                        store.put_event(db,cabinet['device_id'],'irrigation_schedules',datetime.now(timezone.utc),{**schedule,'zone_id':schedule.get('zone_id','zone_a'),'valve_port':schedule.get('valve_port',2),'source':'synthetic_device_spec_v11','collection_version':VERSION,'acquisition_method':'configuration_snapshot'},VERSION+':schedule:'+schedule['name'])
            client=mqtt_client('nextfarm-v11-device-simulator')
            client.on_connect=lambda c,u,f,r,p:state.update(connected=not r.is_failure)
            client.on_disconnect=lambda *a:state.update(connected=False)
            client.connect_async(os.getenv('MQTT_HOST','mosquitto'),int(os.getenv('MQTT_PORT','1883')),30);client.loop_start()
            state['running']=True;rng=random.Random(20260909);tick=0;cycles={};last_alert={};last_truth={};latched=set();pending={}
            while not stop.wait(5):
                now=datetime.now(timezone.utc)
                for index,d in enumerate(devices):
                    device=d['device_id'];scenario=forced.get(device,'normal')
                    phase=(int(now.timestamp()/300)+index*13)%90
                    if scenario=='normal':scenario='power_loss' if phase==11 else 'mqtt_loss' if phase==43 else 'normal'
                    power=scenario!='power_loss';network=scenario!='mqtt_loss' and state['connected']
                    observer={'observed_at':now.isoformat(),'power_confirmed':power,'mqtt_connected':network,'source':'synthetic_independent_observer','collection_version':VERSION,'acquisition_method':'server_observer'}
                    local=now.astimezone(timezone(timedelta(hours=7)))
                    scheduled=local.minute<30 and local.hour%6==0
                    if not scheduled:latched.discard(device)
                    if not power and device in cycles:latched.add(device)
                    elapsed=local.minute*60+local.second
                    outputs=schedule_outputs(elapsed,scheduled,power,device in latched)
                    watering,zone_open,fert=outputs['pump'],outputs['valve'],outputs['fertilizer']
                    payload={'pump_running':watering,'valve_running':zone_open,'fertilizer_requested':fert,'fertilizer_running':fert,
                      'dosage_configured':True,'meter_configured':True,'emergency_stop':False,
                      'pressure':(3 if watering else 0)+max(0,rng.gauss(0,.05)),'pump_current':(4 if watering else 0)+max(0,rng.gauss(0,.05)),'sensor_bus_errors':max(0,rng.gauss(0,.4)),
                      'supply_voltage':24+rng.gauss(0,.1),'rssi':-48+rng.gauss(0,1),
                      'packet_loss_rate':max(0,rng.gauss(.01,.01)),'command_failure_rate':None,
                      'online':True,'power_state':'on','mqtt_state':'connected','flow_rate':12 if watering else 0,
                      'outputs':[{'port':1,'running':watering,'role':'water_pump'},{'port':2,'running':zone_open,'role':'zone_valve','zone_id':'zone_a'},{'port':3,'running':fert,'role':'fertilizer_pump'},{'port':4,'running':fert,'role':'fertilizer_valve','channel':0}],
                      'calibration_valid':True,'calibrated_ml_per_min':24,'fertilizer_stop_latched':device in latched}
                    with store.connect() as db:
                        store.put_event(db,device,'connection_observer',now,observer,'observer:'+now.isoformat())
                        code='POWER_LOSS' if not power else 'MQTT_INTERRUPTED' if not network else 'CONNECTED'
                        if code!=last_alert.get(device):
                            store.put_event(db,device,'alerts',now,{'code':code,'text':connectivity({'observed_at':now.isoformat()},observer)['text'],'source':'synthetic_device_spec_v11','collection_version':VERSION,'acquisition_method':'server_observer'},'alert:'+now.isoformat())
                            last_alert[device]=code
                            store.put_event(db,device,'technical_logs',now,{'event':'connectivity_transition','code':code,'level':'info' if code=='CONNECTED' else 'warning','source':'synthetic_independent_observer','collection_version':VERSION,'acquisition_method':'server_observer'},'technical:'+now.isoformat())
                        bucket=now.replace(minute=now.minute//10*10,second=0,microsecond=0)
                        if last_truth.get(device)!=bucket:
                            truth={k:None for k in ['no_flow','leak','irrigation_abort','sensor_fault','power_loss','mqtt_loss']};truth.update(power_loss=int(not power),mqtt_loss=int(not network),ground_truth_origin='synthetic_latent_incident',source='synthetic_device_spec_v11',collection_version=VERSION,acquisition_method='server_observer')
                            store.put_event(db,device,'incident_ground_truth',now,truth,'truth:'+bucket.isoformat());last_truth[device]=bucket
                    def publish(group,body,stamp=now):
                        packet={'event_id':str(uuid.uuid4()),'device_id':device,'group':group,'observed_at':stamp.isoformat(),'payload':body,'source':'synthetic_device_spec_v11'}
                        client.publish(f'nextfarm/device/{device}/{group}',json.dumps(packet),qos=1);state['published']+=1
                    # Local schedules and counters continue without MQTT. A power interruption
                    # invalidates the counter and latches this cycle until the next schedule.
                    if watering and device not in cycles:
                        cycles[device]={'started_at':now.isoformat(),'water_liters':0.,'fertilizer_ml':0.,'volume_valid':True,'zone_id':'zone_a','valve_port':2,'fertilizer_channel':0}
                        pending.setdefault(device,[]).append(('control_commands',{'requested_by':'local_schedule','command':'start_irrigation','status':'acknowledged'},now))
                    if device in cycles:
                        cycle=cycles[device]
                        if not power:
                            cycle.update(result='interrupted_power',counter_reset=True,volume_valid=False,water_liters=None,fertilizer_ml=None)
                        elif watering:
                            cycle['water_liters']+=payload['flow_rate']*5/60;cycle['fertilizer_ml']+=2 if fert else 0
                        if not watering:
                            run=cycles.pop(device);run.update(ended_at=now.isoformat(),result=run.get('result','completed'),volume_method='synthetic_local_pulse_counter',duration_minutes=(now-datetime.fromisoformat(run['started_at'])).total_seconds()/60)
                            pending.setdefault(device,[]).append(('irrigation_runs',run,now))
                    if power and network:
                        publish('device_status',payload)
                        if tick%12==0:
                            angle=2*math.pi*(now.hour+now.minute/60)/24+index
                            publish('sensor_readings',{'soil_moisture':62+index*3+8*math.sin(angle),
                              'temperature':26+index+5*math.sin(angle),'air_humidity':80-6*math.sin(angle),
                              'ec':1.6+index*.1+.24*math.sin(angle*2/3),'ph':6.1+index*.12+.28*math.sin(angle/2),
                              'flow_rate':payload['flow_rate'],'quality':'good','sensor_point':'sensor_a','zone_id':'zone_a'})
                        for group,record,event_time in pending.pop(device,[]):
                            publish(group,{**record,'replayed':(now-event_time).total_seconds()>5},event_time)
                tick+=1
            client.disconnect();client.loop_stop()
        except Exception as exc:logging.exception('simulator');state.update(running=False,last_error=str(exc))
    @asynccontextmanager
    async def life(app):
        store.initialize_schema();thread=threading.Thread(target=worker,daemon=True);thread.start();yield;stop.set();thread.join(timeout=8)
    app=FastAPI(lifespan=life)
    @app.get('/health')
    def health():return {'status':'ok' if state['running'] else 'starting','version':'12.0.0',**state}
    @app.post('/scenarios/{device_id}/{scenario}')
    def scenario(device_id:str,scenario:str,x_internal_service_key:str|None=Header(default=None)):
        import hmac
        key=os.getenv('INTERNAL_SERVICE_KEY','')
        if not key or not hmac.compare_digest(key,x_internal_service_key or ''):raise HTTPException(401,'Chỉ test harness nội bộ được chọn kịch bản')
        if scenario not in ['normal','power_loss','mqtt_loss']:raise HTTPException(422,'Kịch bản không hỗ trợ')
        forced[device_id]=scenario;return {'device_id':device_id,'scenario':scenario,'source':'simulation'}
    return app
