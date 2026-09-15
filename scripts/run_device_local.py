"""Run the v11 stack locally against existing PostgreSQL/MQTT/Identity containers.

This is a review server, not proof of a successful Docker image build.
Usage: python scripts/run_device_local.py --project-root <directory> --port 19080
"""
import os,sys,argparse,json
from pathlib import Path
from urllib.parse import quote
from contextlib import AsyncExitStack,asynccontextmanager

def configure(root,port):
    for line in (root/'.env').read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1);os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
    os.environ['DATABASE_URL']='postgresql://nextfarm:'+quote(os.environ['POSTGRES_PASSWORD'],safe='')+'@127.0.0.1:15432/nextfarm_support'
    os.environ.update(IDENTITY_URL='http://127.0.0.1:18100',KNOWLEDGE_URL='http://127.0.0.1:18200',
      FARM_DATA_URL=f'http://127.0.0.1:{port}/api/farm',ANALYTICS_URL=f'http://127.0.0.1:{port}/api/analytics',
      MODEL_ARTIFACT_DIR=str(root/'model-artifacts'),MQTT_HOST='127.0.0.1',MQTT_PORT='11883')

def build(root,port):
    configure(root,port)
    from fastapi import FastAPI,Request
    from fastapi.responses import Response
    from fastapi.staticfiles import StaticFiles
    import httpx
    from nextfarm_device.api import data_app,chat_app,analytics_app,catalog_app
    from nextfarm_device.runtime import ingestion_app,simulator_app
    mounted={'farm':data_app(),'chatbot':chat_app(),'analytics':analytics_app(),'router':catalog_app(),
       'telemetry':ingestion_app(),'simulator':simulator_app()}
    @asynccontextmanager
    async def life(app):
        async with AsyncExitStack() as stack:
            for sub in mounted.values():await stack.enter_async_context(sub.router.lifespan_context(sub))
            yield
    app=FastAPI(lifespan=life)
    @app.api_route('/api/{service}/{path:path}',methods=['GET','POST','PUT','DELETE','PATCH'])
    async def proxy(service:str,path:str,request:Request):
        if service not in ['identity','knowledge']:return Response(status_code=404)
        base={'identity':os.environ['IDENTITY_URL'],'knowledge':os.environ['KNOWLEDGE_URL']}[service]
        headers={k:v for k,v in request.headers.items() if k.lower() in ['authorization','content-type']}
        async with httpx.AsyncClient(timeout=30) as client:
            r=await client.request(request.method,base+'/'+path,params=request.query_params,headers=headers,content=await request.body())
        return Response(r.content,status_code=r.status_code,media_type=r.headers.get('content-type'))
    # Mount specific APIs before the generic proxy route.
    proxy_routes=list(app.router.routes);app.router.routes=[]
    for name,sub in mounted.items():app.mount('/api/'+name,sub)
    app.router.routes.extend(proxy_routes)
    @app.get('/health')
    def health():return {'status':'ok','version':'11.0.0','mode':'native_review','docker_build_verified':False}
    ui=Path(__file__).resolve().parents[1]/'apps/device-web'
    if not ui.exists():ui=Path(__file__).resolve().parents[1]/'apps/web'
    app.mount('/',StaticFiles(directory=ui,html=True),name='web')
    return app

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--port',type=int,default=19080)
    args=p.parse_args();sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import uvicorn
    uvicorn.run(build(args.project_root,args.port),host='127.0.0.1',port=args.port)
