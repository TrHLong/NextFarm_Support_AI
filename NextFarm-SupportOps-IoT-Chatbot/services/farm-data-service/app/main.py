from __future__ import annotations
import os
from fastapi import FastAPI, HTTPException, Query
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv('DATABASE_URL')
app = FastAPI(title='NextFarm Farm Data Service', version='0.1.0')

def conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

@app.get('/health')
def health():
    return {'service':'farm-data-service','status':'ok'}

@app.get('/farms/{farm_id}')
def farm(farm_id: str):
    with conn() as db, db.cursor() as cur:
        cur.execute('SELECT * FROM farm.farms WHERE farm_id=%s', (farm_id,))
        f = cur.fetchone()
        if not f: raise HTTPException(404, 'farm not found')
        cur.execute('SELECT zone_id,zone_code,zone_name,area_ha,target_moisture_min,target_moisture_max FROM farm.plot_zones WHERE farm_id=%s ORDER BY zone_code', (farm_id,))
        zones = cur.fetchall()
    return {**f, 'zones': zones}

@app.get('/farms/{farm_id}/moisture/latest')
def latest_moisture(farm_id: str, zone: str = Query('A')):
    with conn() as db, db.cursor() as cur:
        cur.execute("""SELECT z.zone_code,z.zone_name,z.target_moisture_min,z.target_moisture_max,r.*
                       FROM farm.plot_zones z
                       LEFT JOIN LATERAL (
                         SELECT * FROM iot.sensor_readings r
                         WHERE r.zone_id=z.zone_id AND r.metric_type='soil_moisture'
                         ORDER BY r.timestamp_utc DESC LIMIT 1
                       ) r ON true
                       WHERE z.farm_id=%s AND upper(z.zone_code)=upper(%s)""", (farm_id, zone))
        row = cur.fetchone()
    if not row or not row['reading_id']:
        raise HTTPException(404, 'no moisture data')
    value = float(row['value'])
    status = 'low' if value < float(row['target_moisture_min']) else 'high' if value > float(row['target_moisture_max']) else 'normal'
    return {'farm_id': farm_id, 'zone_code': row['zone_code'], 'zone_name': row['zone_name'], 'value': value, 'unit': row['unit'], 'timestamp_utc': row['timestamp_utc'], 'quality': row['quality'], 'target_min': float(row['target_moisture_min']), 'target_max': float(row['target_moisture_max']), 'status': status}

@app.get('/farms/{farm_id}/devices/port/{port_number}')
def port_status(farm_id: str, port_number: int):
    with conn() as db, db.cursor() as cur:
        cur.execute("""SELECT p.port_id,p.port_number,p.port_name,p.port_type,z.zone_code,d.device_id,d.model_name,
                              s.online,s.running,s.last_seen_utc,s.timestamp_utc
                       FROM iot.device_ports p
                       JOIN iot.devices d ON d.device_id=p.device_id
                       LEFT JOIN farm.plot_zones z ON z.zone_id=p.zone_id
                       LEFT JOIN LATERAL (
                         SELECT * FROM iot.device_status_events se
                         WHERE se.port_id=p.port_id ORDER BY se.timestamp_utc DESC LIMIT 1
                       ) s ON true
                       WHERE d.farm_id=%s AND p.port_number=%s
                       ORDER BY d.device_id, p.port_id""", (farm_id, port_number))
        rows = cur.fetchall()
    if not rows:
        return {'configured': False, 'message': f'Van/cổng số {port_number} chưa có trong cấu hình vườn.', 'items': []}
    return {'configured': True, 'items': rows, 'ambiguous': len(rows) > 1}

@app.get('/farms/{farm_id}/alerts')
def alerts(farm_id: str, zone: str | None = None, limit: int = 5):
    with conn() as db, db.cursor() as cur:
        params = [farm_id]
        where = 'a.farm_id=%s'
        if zone:
            where += ' AND upper(z.zone_code)=upper(%s)'
            params.append(zone)
        params.append(limit)
        cur.execute(f"""SELECT a.*,z.zone_code,c.title_vi AS checklist_title
                        FROM iot.alerts a
                        LEFT JOIN farm.plot_zones z ON z.zone_id=a.zone_id
                        LEFT JOIN support.ticket_checklists c ON c.checklist_id=a.suggested_checklist_id
                        WHERE {where}
                        ORDER BY a.created_at DESC LIMIT %s""", params)
        rows = cur.fetchall()
    return {'items': rows, 'total': len(rows)}

@app.get('/farms/{farm_id}/irrigation/summary')
def irrigation_summary(farm_id: str, zone: str | None = None):
    with conn() as db, db.cursor() as cur:
        params = [farm_id]
        where = "r.farm_id=%s AND r.started_at >= date_trunc('day', now())"
        if zone:
            where += ' AND upper(z.zone_code)=upper(%s)'
            params.append(zone)
        cur.execute(f"""SELECT count(*) AS run_count, coalesce(sum(duration_minutes),0) AS total_minutes,
                               coalesce(sum(water_liters),0) AS total_liters
                        FROM iot.irrigation_runs r
                        LEFT JOIN farm.plot_zones z ON z.zone_id=r.zone_id
                        WHERE {where}""", params)
        row = cur.fetchone()
    return {'farm_id': farm_id, 'zone': zone, 'run_count': row['run_count'], 'total_minutes': float(row['total_minutes']), 'total_liters': float(row['total_liters'])}
