"""Optional FastAPI transport around the same application service."""
import asyncio
import json
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

import server
from ai_report import read_findings, render_html


@asynccontextmanager
async def lifespan(app):
    server.init()
    server.STOP.clear()
    thread=threading.Thread(target=server.scheduler,daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.STOP.set()
        thread.join(timeout=2)


app=FastAPI(title="Cyber Garden",version="1.0",lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=["localhost","127.0.0.1"])
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173","http://127.0.0.1:5173"],
                   allow_methods=["GET","POST","PUT","DELETE"],allow_headers=["Content-Type","Last-Event-ID"])


async def endpoint(request:Request):
    path=request.url.path
    try:
        body={}
        if request.method in ("POST","PUT"):
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>18*1024*1024:
                    raise HTTPException(413,"Request too large")
            if raw:
                if request.headers.get("content-type","").split(";")[0]!="application/json":
                    raise HTTPException(415,"Use application/json")
                body=json.loads(raw)
                if not isinstance(body,dict):
                    raise ValueError("Expected object")
        if path.endswith("/events") and "text/event-stream" in request.headers.get("accept",""):
            initial=int(request.headers.get("last-event-id","0"))
            runpath=path.rsplit("/",1)[0]
            await asyncio.to_thread(server.dispatch,"GET",runpath,{})
            async def events():
                last=initial
                while not await request.is_disconnected():
                    state=await asyncio.to_thread(server.dispatch,"GET",runpath,{})
                    for event in await asyncio.to_thread(server.dispatch,"GET",path,{}):
                        if event["seq"]>last:
                            last=event["seq"]
                            yield f"id: {last}\ndata: {json.dumps(event)}\n\n"
                    if state["status"] in ("success","failed"):
                        break
                    await asyncio.sleep(.4)
            return StreamingResponse(events(),media_type="text/event-stream")
        if path.endswith(("/report.html","/submission.json")):
            report=await asyncio.to_thread(server.dispatch,"GET",path.rsplit("/",1)[0]+"/report",{})
            if path.endswith(".json"):
                return report["submission"]
            return HTMLResponse(server.display_report(report))
        return await asyncio.to_thread(server.dispatch,request.method,path,body)
    except HTTPException:
        raise
    except (KeyError,ValueError,TypeError) as exc:
        raise HTTPException(400,str(exc)[:240]) from exc
    except LookupError as exc:
        raise HTTPException(404,str(exc)) from exc


ROUTES={
    "GET":["health","nodes","settings","findings","projects","projects/{id}","workflows","workflows/{id}",
           "workflows/{id}/versions","runs","runs/{id}","runs/{id}/events","runs/{id}/report","runs/{id}/report.html","runs/{id}/submission.json","inbox"],
    "POST":["projects","workflows","workflows/validate","workflows/{id}/validate","workflows/{id}/runs","inbox"],
    "PUT":["projects/{id}","workflows/{id}","workflows/{id}/schedule"],
    "DELETE":["projects/{id}","workflows/{id}"],
}
for verb,paths in ROUTES.items():
    for path in paths:
        app.add_api_route(server.BASE+"/"+path,endpoint,methods=[verb],name=verb+" "+path)
