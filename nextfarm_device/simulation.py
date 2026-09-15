"""Synthetic ESP32-S3 cabinet experiment, NOT NextFarm measured hardware data.

Independent latent degradation episodes cause physical outcomes later. Only
noisy telemetry preceding the outcome is exposed to feature engineering.
Hidden states, scenario IDs and future events live in a separate ground-truth CSV.
All timing, noise and risk frequencies below are explicit assumptions.
"""
from pathlib import Path
import hashlib, json
import numpy as np
import pandas as pd

FAULTS=['no_flow','leak','irrigation_abort','sensor_fault','power_loss','mqtt_loss']

def generate_site(site, days=42, seed=20260909, end='2026-09-09T00:00:00Z'):
    rng=np.random.default_rng(seed+site*10007)
    n=days*144
    times=pd.date_range(end=pd.Timestamp(end),periods=n,freq='10min')
    t=np.arange(n); hour=(times.hour.to_numpy()+times.minute.to_numpy()/60)
    profile=site%3
    metrics={}
    # Device-specific phases/noise, shared profile types across customers.
    for key,base,amp,period,noise in [('soil_moisture',62+profile*3,8,144,.12),
              ('temperature',26+profile,5,144,.09),('ec',1.6+profile*.1,.24,216,.004),('ph',6.1+profile*.12,.28,288,.004)]:
        phase=rng.uniform(0,2*np.pi)
        drift=np.cumsum(rng.normal(0,noise/6,n))
        metrics[key]=base+rng.normal(0,.2)+amp*np.sin(t*2*np.pi/period+phase)+drift+rng.normal(0,noise,n)
    metrics['air_humidity']=80-1.3*(metrics['temperature']-26)+rng.normal(0,1,n)
    latent=np.zeros((n,6)); event=np.zeros((n,6),dtype=int)
    episodes=[]
    for j,fault in enumerate(FAULTS):
        cursor=int(rng.integers(18,100))
        while cursor<n-24:
            length=int(rng.integers(10,22)); duration=int(rng.integers(3,9))
            start=cursor; incident=min(n-1,start+length)
            latent[start:incident,j]=np.linspace(.05,1,length)
            event[incident:min(n,incident+duration),j]=1
            latent[incident:min(n,incident+duration),j]=1
            episodes.append({'event_type':fault,'started_at':times[incident].isoformat(),
                 'ended_at':times[min(n-1,incident+duration)].isoformat(),'ground_truth_origin':'synthetic_latent_incident',
                 'independent_of_feature_threshold':True})
            cursor=incident+duration+int(rng.integers(100,240))
    watering=((t%36)<3).astype(int)
    power=(event[:,4]==0); mqtt=(event[:,5]==0)
    actual_pump=watering*power*(1-event[:,2])
    status=pd.DataFrame({'observed_at':times,'pump_running':actual_pump,
        'valve_running':watering*power,'fertilizer_requested':watering,
        'fertilizer_running':actual_pump*(event[:,0]==0),
        'dosage_configured':True,'meter_configured':True,'emergency_stop':False,
        'supply_voltage':24-5.3*latent[:,4]+rng.normal(0,.13,n),
        'rssi':-48-36*latent[:,5]+rng.normal(0,1,n),
        'pressure':3-2*latent[:,0]-.8*latent[:,1]+rng.normal(0,.04,n),
        'pump_current':4+3*latent[:,2]+rng.normal(0,.06,n),
        'sensor_bus_errors':np.maximum(0,25*latent[:,3]+rng.normal(0,.5,n)),
        'packet_loss_rate':np.clip(latent[:,5]*.65+rng.normal(0,.025,n),0,1),
        'command_failure_rate':np.clip(latent[:,2]*.4+rng.normal(0,.018,n),0,1),
        'power_state':np.where(power,'on','off'),'mqtt_state':np.where(mqtt,'connected','disconnected'),
        'online':power & mqtt,'source':'synthetic_device_spec_v11'})
    metrics['flow_rate']=np.maximum(0,actual_pump*(12-5*latent[:,0])*(1-event[:,0])+2.5*event[:,1]+rng.normal(0,.08,n))
    sensor=pd.DataFrame({'observed_at':times,**metrics})
    sensor['quality']=np.where(event[:,3],'bad','good')
    sensor['source']='synthetic_device_spec_v11'
    # No packets from an unpowered/unconnected cabinet. Observer evidence is independent.
    outage=(~power)|(~mqtt)
    sensor=sensor.loc[~outage].copy()
    status_packets=status.loc[~outage].copy()
    # Missing is genuinely absent, not zero/offline. Causal feature builder preserves NaN.
    missing=rng.random(len(sensor))<.012
    sensor.loc[missing,'ec']=np.nan
    truth=pd.DataFrame({'observed_at':times,**{f:event[:,i] for i,f in enumerate(FAULTS)}})
    truth['ground_truth_origin']='synthetic_latent_incident'
    runs=[]; commands=[]
    for k in np.flatnonzero((t%36)==0):
        stop=min(n-1,k+3); power_cut=bool((~power[k:stop]).any())
        failed=bool(event[k:stop,2].any() or power_cut or event[k:stop,0].any())
        liters=float(np.maximum(metrics['flow_rate'][k:stop],0).sum()*10)
        runs.append({'run_id':f'run_{site}_{k}','started_at':times[k].isoformat(),'ended_at':times[stop].isoformat(),
            'duration_minutes':30,'water_liters':None if power_cut else round(liters,2),'fertilizer_ml':None if power_cut else round(liters*.8 if not failed else 0,2),
            'volume_valid':not power_cut,'counter_reset':power_cut,'replayed':bool((~mqtt[k:stop]).any()),
            'fertilizer_channel':1,'result':'interrupted' if failed else 'completed','volume_method':'synthetic_pulse_counter'})
        commands.append({'command_id':f'cmd_{site}_{k}','requested_at':times[k].isoformat(),
            'requested_by':'local_schedule','command':'start_irrigation','status':'not_acknowledged' if not power[k] else 'acknowledged','replayed':bool(not mqtt[k])})
    return sensor,status_packets,truth,pd.DataFrame(runs),pd.DataFrame(commands),pd.DataFrame(episodes)

def generate_dataset(root, sites=12, days=42, seed=20260909):
    root=Path(root); manifest={'source':'synthetic_device_spec_v11','real_customer_count':0,
       'synthetic_customer_count':sites,'days':days,'seed':seed,'sensor_storage_seconds':600,
       'device_wire_seconds':5,'offline_training_status_seconds':600,
       'status_note':'Offline CSV samples the simulated 5-second state at 10-minute boundaries; NOT a count of every MQTT packet.',
       'ground_truth':'Latent simulator incidents; not field-verified incidents. No label or scenario ID is a feature.',
       'source_spec':'Chat-thiet-bi-NextFarm-v0.1.html 09/09/2026',
       'assumptions':'Dynamics, precursor strength, failure rate and numerical ranges are declared simulator assumptions, not empirically calibrated.',
       'files':[]}
    for site in range(sites):
        customer=f'synthetic_customer_{site:03d}'; device=f'cabinet_{site:03d}'
        target=root/'customers'/customer; target.mkdir(parents=True,exist_ok=True)
        frames=generate_site(site,days,seed)
        for name,df in zip(['sensor_readings','device_status','incident_ground_truth','irrigation_runs','control_commands','incidents'],frames):
            df.insert(0,'device_id',device);df.insert(0,'customer_id',customer)
            path=target/f'{name}.csv';df.to_csv(path,index=False)
            manifest['files'].append({'path':str(path.relative_to(root)),'rows':len(df),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        config={'customer_id':customer,'device_id':device,'synthetic':True,'model':'ESP32-S3 8DI/8DO',
            'profile_type':['greenhouse','open_field','net_house'][site%3], 'firmware':'simulator-v11',
            'sensor_seconds':600,'status_seconds':5,'thresholds':{'soil_moisture':[55,75],'temperature':[18,32],'ec':[1,2.5],'ph':[5.5,7]},
            'outputs':[{'port':1,'role':'water_pump'},{'port':2,'role':'zone_valve'},{'port':3,'role':'fertilizer_pump'}],
            'schedules':[{'name':'Tưới định kỳ mô phỏng','every_hours':6,'duration_minutes':30,'fertilizer_ml':288}]}
        (target/'device_profile.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
        pd.DataFrame(config['schedules']).assign(customer_id=customer,device_id=device).to_csv(target/'irrigation_schedules.csv',index=False)
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest
