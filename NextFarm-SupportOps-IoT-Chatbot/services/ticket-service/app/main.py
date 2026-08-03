from __future__ import annotations
import os, uuid
from fastapi import FastAPI
from pydantic import BaseModel
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv('DATABASE_URL')
app = FastAPI(title='NextFarm Ticket Service', version='0.1.0')

def conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

class TicketRequest(BaseModel):
    user_id: str | None = None
    lead_id: str | None = None
    farm_id: str | None = None
    zone_id: str | None = None
    title: str
    description: str
    category: str = 'CHATBOT_HANDOFF'
    priority: str = 'normal'
    product_module_id: str | None = None

@app.get('/health')
def health():
    return {'service':'ticket-service','status':'ok'}

@app.post('/tickets')
def create_ticket(payload: TicketRequest):
    ticket_id = 'ticket_' + uuid.uuid4().hex[:12]
    with conn() as db, db.cursor() as cur:
        cur.execute("""INSERT INTO support.support_tickets(ticket_id,user_id,lead_id,farm_id,zone_id,title,description,product_module_id,category,priority,status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open') RETURNING *""", (ticket_id, payload.user_id, payload.lead_id, payload.farm_id, payload.zone_id, payload.title, payload.description, payload.product_module_id, payload.category, payload.priority))
        row = cur.fetchone()
        db.commit()
    return row

@app.get('/tickets')
def tickets():
    with conn() as db, db.cursor() as cur:
        cur.execute('SELECT * FROM support.support_tickets ORDER BY created_at DESC LIMIT 50')
        rows = cur.fetchall()
    return {'items': rows, 'total': len(rows)}
