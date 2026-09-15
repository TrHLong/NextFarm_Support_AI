"""Extract only approved, device-scoped company reference chunks; no external LLM."""
import re
from .answers import norm
from . import store

STOP={'la','va','cua','co','cho','toi','the','nao','gi','bao','nhieu','sao','khi','ve','duoc','mot','nhung','hay','thi','voi','khong'}
def terms(text):return set(re.findall(r'\w+',norm(text)))-STOP

def retrieve(question):
    query=terms(question)
    with store.connect() as db:
        rows=db.execute('''SELECT c.chunk_id,c.content_vi,c.heading,d.title,s.source_url,d.checksum
          FROM knowledge_db.document_chunks c JOIN knowledge_db.documents d ON d.document_id=c.document_id
          JOIN knowledge_db.sources s ON s.source_id=d.source_id
          WHERE d.active=true AND d.approved=true AND s.active=true AND d.category='DEVICE_SPEC_V11'
          ORDER BY c.chunk_id''').fetchall()
    scored=sorted([(len(query & terms(r['content_vi'])),r) for r in rows],key=lambda x:x[0],reverse=True)
    if not scored or scored[0][0]<2:return {'answerable':False,'reason':'Chưa có đoạn hướng dẫn thiết bị đã duyệt phù hợp'}
    score,row=scored[0]
    if score/max(1,len(query))<.5:return {'answerable':False,'reason':'Bằng chứng tri thức chưa đủ liên quan'}
    return {'answerable':True,'answer':'Trích hướng dẫn đã duyệt (không phải số đo hiện tại):\n'+row['content_vi'][:1400],
       'source':{'title':row['title'],'section':row['heading'],'chunk_id':row['chunk_id'],'source_url':row['source_url'],'checksum':row['checksum']},
       'method':'approved_scoped_extract','lexical_overlap':score,'confidence':None}
