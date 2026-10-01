"""Reproducible canonical three-farmer/three-day dataset for Problem B.

The output is intentionally JSONL and self-describing so it can be imported by
the existing farm-data service without making ML claims from synthetic data.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse, json, random

TZ = timezone(timedelta(hours=7))
SEED = 20260925

def generate(out: Path):
    rng = random.Random(SEED)
    farmers = [('farmer_001','farm_001','device_001','cà chua'),('farmer_002','farm_002','device_002','dưa leo'),('farmer_003','farm_003','device_003','ớt')]
    tables = {name: [] for name in ('farmer','farm','zone','device','sensor_reading','device_state','irrigation_schedule','irrigation_event','fertilizer_event','command_log','alert')}
    base = datetime(2026,9,20,0,0,tzinfo=TZ)
    for fi,(farmer,farm,device,crop) in enumerate(farmers):
        tables['farmer'].append({'farmer_id':farmer,'name':f'Nông dân {fi+1}'})
        tables['farm'].append({'farm_id':farm,'farmer_id':farmer,'name':f'Vườn {crop.title()}','crop':crop})
        for zone in ('A','B'):
            zid=f'zone_{zone.lower()}'; tables['zone'].append({'zone_id':zid,'farm_id':farm,'name':f'Khu {zone}'})
        tables['device'].append({'device_id':device,'farm_id':farm,'name':f'Tủ {crop}','timezone':'Asia/Ho_Chi_Minh'})
        for day in range(3):
            for slot in range(144):
                ts=base+timedelta(days=day,minutes=slot*10,seconds=fi)
                for zone in ('A','B'):
                    zid=f'zone_{zone.lower()}'; phase=(slot+fi*7+(0 if zone=='A' else 3))/18
                    tables['sensor_reading'].append({'farmer_id':farmer,'farm_id':farm,'device_id':device,'zone_id':zid,'timestamp':ts.isoformat(),'soil_moisture_pct':round(62+5*__import__('math').sin(phase),2),'air_temperature_c':round(27+4*__import__('math').sin(phase/2),2),'air_humidity_pct':round(72-8*__import__('math').sin(phase/2),2),'ec':round(1.7+.12*__import__('math').sin(phase),3),'ph':round(6.1+.08*__import__('math').sin(phase),3),'flow_rate_lpm':0.0})
                online=not (day==2 and 9<=slot<=12 and fi==1)
                tables['device_state'].append({'farmer_id':farmer,'farm_id':farm,'device_id':device,'timestamp':ts.isoformat(),'online':online,'pump_on':False,'valve_1_open':False,'valve_2_open':False,'fertilizer_pump_on':False,'active_fertilizer_channel':None,'flow_rate_lpm':0.0,'quality':'missing' if day==1 and 40<=slot<=44 else 'good'})
            tables['irrigation_schedule'].append({'farmer_id':farmer,'farm_id':farm,'device_id':device,'zone_id':'zone_a','schedule_id':f'{device}_schedule_{day+1}','start_time':(base+timedelta(days=day,hours=6)).isoformat(),'duration_minutes':30,'fertilizer_ml':120,'enabled':True})
            for run in range(2):
                start=base+timedelta(days=day,hours=6+run*8,minutes=fi)
                failed=(day==2 and fi==2 and run==1)
                event={'farmer_id':farmer,'farm_id':farm,'device_id':device,'zone_id':'zone_a','event_id':f'{device}_run_{day}_{run}','started_at':start.isoformat(),'ended_at':(start+timedelta(minutes=30)).isoformat(),'duration_minutes':30,'water_liters':None if failed else round(320+rng.random()*40,2),'flow_rate_lpm':None if failed else round(10+rng.random(),2),'fertilizer_ml':None if failed else 120.0,'fertilizer_channel':'channel_1','result':'failed' if failed else 'completed','failure_reason':'no_flow' if failed else None}
                tables['irrigation_event'].append(event); tables['fertilizer_event'].append({**event,'fertilizer_event_id':event['event_id']+'_fert'})
                tables['command_log'].append({'farmer_id':farmer,'farm_id':farm,'device_id':device,'zone_id':'zone_a','timestamp':start.isoformat(),'requested_by':'local_schedule' if run==0 else 'farmer','command':'start_irrigation','status':'failed' if failed else 'success'})
            if day==1: tables['alert'].append({'farmer_id':farmer,'farm_id':farm,'device_id':device,'zone_id':'zone_a','timestamp':(base+timedelta(days=day,hours=10)).isoformat(),'code':'sensor_stale','severity':'warning','status':'open'})
            if day==2 and fi==2: tables['alert'].append({'farmer_id':farmer,'farm_id':farm,'device_id':device,'zone_id':'zone_a','timestamp':(base+timedelta(days=day,hours=14)).isoformat(),'code':'no_flow','severity':'critical','status':'open'})
    out.mkdir(parents=True,exist_ok=True)
    manifest={'dataset_status':'PIPELINE_TEST_ONLY','seed':SEED,'timezone':'Asia/Ho_Chi_Minh','farmers':3,'days':3,'tables':{}}
    for name,rows in tables.items():
        path=out/f'{name}.jsonl'; path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf-8'); manifest['tables'][name]=len(rows)
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',default='data/canonical_reset'); args=parser.parse_args(); print(json.dumps(generate(Path(args.output)),ensure_ascii=False,indent=2))
