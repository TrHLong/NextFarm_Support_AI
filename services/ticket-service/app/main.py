from fastapi import FastAPI,HTTPException
app=FastAPI(title="Retired ticket workflow")
@app.api_route("/{path:path}",methods=["GET","POST","PUT","PATCH","DELETE"])
def retired(path:str):
    raise HTTPException(410,"Luồng ticket đã ngừng sử dụng ở phiên bản thiết bị v11")
