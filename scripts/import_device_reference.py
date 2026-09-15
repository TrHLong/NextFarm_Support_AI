"""Import the supplied company HTML as a draft. Human approval remains visible.
Run inside farm-data-service after build; uses existing DATABASE_URL.
"""
import sys,hashlib
from pathlib import Path
from html.parser import HTMLParser
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nextfarm_device import store
from psycopg.types.json import Jsonb

class Sections(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.heading='Giới thiệu';self.text=[];self.inheading=False;self.skip=0
    def flush(self):
        value=' '.join(' '.join(self.text).split())
        if value:self.rows.append((self.heading,value))
        self.text=[]
    def handle_starttag(self,tag,attrs):
        if tag in ['script','style']:self.skip+=1
        if tag in ['h1','h2','h3']:self.flush();self.inheading=True;self.heading=''
    def handle_endtag(self,tag):
        if tag in ['script','style']:self.skip=max(0,self.skip-1)
        if tag in ['h1','h2','h3']:self.inheading=False
    def handle_data(self,text):
        if self.skip:return
        if self.inheading:self.heading+=text
        else:self.text.append(text)

def import_reference(path):
    raw=Path(path).read_bytes();digest=hashlib.sha256(raw).hexdigest();parser=Sections();parser.feed(raw.decode('utf-8-sig'));parser.flush()
    doc='device_spec_v11_'+digest[:12];content='\n\n'.join(h+'\n'+t for h,t in parser.rows)
    with store.connect() as db:
        db.execute("INSERT INTO knowledge_db.sources(source_id,source_name,source_url,domain,source_type,trust_tier,usage_note) VALUES ('device_spec_company_v11','Tài liệu thiết bị công ty do người dùng cung cấp','nextfarm-local://device-spec-v0.1','local','internal',1,'HTML nguồn được giữ nguyên trong docs/references; bắt buộc duyệt') ON CONFLICT(source_id) DO NOTHING")
        db.execute("INSERT INTO knowledge_db.documents(document_id,source_id,title,category,summary_vi,content_vi,checksum,approved) VALUES (%s,'device_spec_company_v11','Chat thiết bị NextFarm v0.1 do công ty cung cấp','DEVICE_SPEC_V11',%s,%s,%s,false) ON CONFLICT(document_id) DO NOTHING",(doc,content[:500],content,digest))
        for i,(heading,text) in enumerate(parser.rows):
            db.execute('''INSERT INTO knowledge_db.document_chunks(chunk_id,document_id,chunk_order,content_vi,token_estimate,metadata,heading,section_path,source_locator,approved_snapshot)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,false) ON CONFLICT(chunk_id) DO NOTHING''',(f'{doc}_{i}',doc,i,text,len(text.split()),Jsonb({'source_sha256':digest,'original_file':Path(path).name}),heading,heading,f'nextfarm-local://device-spec-v0.1#section-{i}'))
    return {'document_id':doc,'sections':len(parser.rows),'sha256':digest,'approval':'existing approval retained or new draft; no automatic approval'}

if __name__=='__main__':
    print(import_reference(sys.argv[1] if len(sys.argv)>1 else '/app/device-reference.html'))
