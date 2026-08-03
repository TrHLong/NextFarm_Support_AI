from __future__ import annotations
import os, re, unicodedata
from fastapi import FastAPI
from pydantic import BaseModel
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv('DATABASE_URL')
app = FastAPI(title='NextFarm Knowledge Service', version='0.1.0')

def conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def normalize(text: str) -> str:
    text = unicodedata.normalize('NFD', text or '')
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    return re.sub(r'[^a-z0-9\s]', ' ', text.lower().replace('đ','d')).strip()

def tokens(text: str) -> set[str]:
    stop = {'toi','anh','chi','la','gi','co','khong','muon','can','hoi','ve','thi','nhu','the','nao','cho'}
    return {t for t in normalize(text).split() if len(t) > 1 and t not in stop}

class Query(BaseModel):
    question: str
    user_type: str | None = None

@app.get('/health')
def health():
    return {'service':'knowledge-service','status':'ok'}

@app.get('/articles')
def articles():
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT article_id,title,topic,status FROM knowledge.knowledge_articles ORDER BY topic,title")
        rows = cur.fetchall()
    return {'items': rows, 'total': len(rows)}

@app.post('/query')
def query(payload: Query):
    q = tokens(payload.question)
    if not q:
        return {'answerable': False, 'reason': 'Câu hỏi quá ngắn.', 'items': []}
    with conn() as db, db.cursor() as cur:
        cur.execute("""SELECT a.article_id,a.title,a.topic,a.body_vi,a.status,s.title AS source_title,s.url
                       FROM knowledge.knowledge_articles a
                       LEFT JOIN knowledge.knowledge_sources s ON s.source_id=a.source_id
                       WHERE a.status='approved'""")
        rows = cur.fetchall()
    scored = []
    for r in rows:
        content = f"{r['title']} {r['topic']} {r['body_vi']}"
        overlap = q & tokens(content)
        score = len(overlap)
        if {'nextfarm','nen','tang','he','sinh','thai'} & q and r['topic'] == 'platform_ecosystem': score += 6
        if {'tuoi','nuoc','van'} & q and r['topic'] == 'irrigation': score += 4
        if {'nmc','khi','hau','nhiet'} & q and r['topic'] == 'nmc': score += 4
        if {'fertikit','cham','phan','ec','ph'} & q and r['topic'] == 'fertigation': score += 4
        if {'gis','lo','khu','ban','do'} & q and r['topic'] == 'gis': score += 4
        if score:
            scored.append((score, r, sorted(overlap)))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored or scored[0][0] < 2:
        return {'answerable': False, 'reason': 'Kho tri thức chưa có nguồn đủ chắc để trả lời.', 'items': []}
    best = scored[0][1]
    prefix = 'Theo kho tri thức NextFarm:'
    return {'answerable': True, 'answer': f"{prefix} {best['body_vi']}", 'source': {'article_id': best['article_id'], 'title': best['title'], 'url': best['url']}, 'items': [{'article_id': x[1]['article_id'], 'title': x[1]['title'], 'score': x[0]} for x in scored[:3]]}
