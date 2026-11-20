"""Local REST service for a single Cyber Garden workspace."""
import base64
import io
import json
import os
import re
import sqlite3
import threading
import time
import uuid
import zipfile
from html import escape
from cryptography.fernet import Fernet
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from workflow import DEFAULT, TYPES, execute, validate
from timing import parse_cron, due
from ai_report import render_html

ROOT=Path(os.getenv("GARDEN_DATA",Path(__file__).with_name("data")))
PORT=int(os.getenv("GARDEN_PORT","8765"))
BASE="/api/v1"
LIMIT=12*1024*1024
OFFICIAL="https://github.com/TBagirov/training"
POOL=ThreadPoolExecutor(max_workers=1)
STOP=threading.Event()


def conn():
    return sqlite3.connect(ROOT/"garden.sqlite",timeout=15)


def sql(query,args=(),fetch=False):
    with closing(conn()) as db, db:
        cursor=db.execute(query,args)
        return cursor.fetchall() if fetch else cursor.rowcount


def init():
    ROOT.mkdir(parents=True,exist_ok=True)
    if not (ROOT/"source.key").exists():
        with (ROOT/"source.key").open("xb") as key:
            key.write(Fernet.generate_key())
    with closing(conn()) as db, db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,files TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY,project TEXT NOT NULL,name TEXT NOT NULL,graph TEXT NOT NULL,version INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS versions(id TEXT,version INTEGER,graph TEXT,PRIMARY KEY(id,version));
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,workflow TEXT,version INTEGER,status TEXT,result TEXT,error TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,run TEXT,node TEXT,status TEXT,payload TEXT,created REAL);
        CREATE INDEX IF NOT EXISTS run_events ON events(run,seq);
        CREATE TABLE IF NOT EXISTS schedules(workflow TEXT PRIMARY KEY,minutes INTEGER,next REAL);
        CREATE TABLE IF NOT EXISTS cron_jobs(workflow TEXT PRIMARY KEY,expr TEXT,zone TEXT,last INTEGER);
        CREATE TABLE IF NOT EXISTS inbox(id INTEGER PRIMARY KEY,message TEXT);
        """)
        db.execute("UPDATE runs SET status='failed',error='Server restarted' WHERE status IN ('queued','running')")


def source_cipher():
    return Fernet((ROOT/"source.key").read_bytes())


def read_source(stored):
    if isinstance(stored,str):
        return json.loads(stored)
    return json.loads(source_cipher().decrypt(stored))


def one(query,args):
    rows=sql(query,args,True)
    if not rows:
        raise LookupError("Record not found")
    return rows[0]


def display_report(report):
    if report["ai"] is not None:
        return render_html(report["ai"])
    items=[]
    for row in report["submission"]["findings"]:
        location=row["path"] + (":"+str(row["line"]) if "line" in row else "")
        subject=row.get("class") or f"{row['group']}:{row['artifact']}:{row['version']} — {row['advisoryId']}"
        items.append("<li><strong>"+escape(subject)+"</strong> · "+escape(row["severity"])+" · <code>"+escape(location)+"</code></li>")
    content="<ul>"+"".join(items)+"</ul>" if items else "<p>Находок нет.</p>"
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Отчёт проверки</title><h1>Результаты анализаторов</h1>'+content+"</html>"


def unpack(data):
    if len(data)>LIMIT:
        raise ValueError("Archive too large")
    files={}
    total=0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist())>3000:
            raise ValueError("Too many files")
        for info in archive.infolist():
            name=info.filename.replace("\\","/")
            path=PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or ":" in name or (info.external_attr>>16)&0o170000==0o120000:
                raise ValueError("Invalid ZIP entry")
            total+=info.file_size
            if total>40*1024*1024:
                raise ValueError("Archive expands beyond limit")
            if info.is_dir() or not (name.endswith((".kt",".kts",".yml",".yaml",".properties",".lockfile"))):
                continue
            if info.file_size>1024*1024 or name in files:
                raise ValueError("Oversized or duplicate source")
            files[name]=archive.read(info).decode("utf-8-sig")
    roots=[p[:-len("build.gradle.kts")] for p in files if PurePosixPath(p).name=="build.gradle.kts"]
    if not roots:
        raise ValueError("build.gradle.kts missing")
    prefix=min(roots,key=len)
    return {p[len(prefix):]:v for p,v in files.items() if p.startswith(prefix)}


def save_workflow(body,ident=None):
    graph=body["graph"]
    validate(graph)
    name=title(body)
    with closing(conn()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if ident is None:
            ident=uuid.uuid4().hex
            project=body["project_id"]
            if not db.execute("SELECT 1 FROM projects WHERE id=?",(project,)).fetchone():
                raise LookupError("Unknown project")
            ver=1
            db.execute("INSERT INTO workflows VALUES(?,?,?,?,?)",(ident,project,name,json.dumps(graph),ver))
        else:
            row=db.execute("SELECT version FROM workflows WHERE id=?",(ident,)).fetchone()
            if not row:
                raise LookupError("Unknown workflow")
            ver=row[0]+1
            db.execute("UPDATE workflows SET name=?,graph=?,version=? WHERE id=?",(name,json.dumps(graph),ver,ident))
        db.execute("INSERT INTO versions VALUES(?,?,?)",(ident,ver,json.dumps(graph)))
    return {"id":ident,"version":ver}


def title(body):
    name=body.get("name")
    if not isinstance(name,str) or not 1<=len(name.strip())<=160:
        raise ValueError("Provide a project or workflow name")
    return name.strip()


def remove_record(kind, ident):
    with closing(conn()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if kind=="projects":
            if not db.execute("SELECT 1 FROM projects WHERE id=?",(ident,)).fetchone():
                raise LookupError("Unknown project")
            ids=[w for w, in db.execute("SELECT id FROM workflows WHERE project=?",(ident,))]
        else:
            if not db.execute("SELECT 1 FROM workflows WHERE id=?",(ident,)).fetchone():
                raise LookupError("Unknown workflow")
            ids=[ident]
        for wid in ids:
            if db.execute("SELECT 1 FROM runs WHERE workflow=? AND status IN ('running','queued')",(wid,)).fetchone():
                raise ValueError("Wait until active runs finish")
            db.execute("DELETE FROM cron_jobs WHERE workflow=?",(wid,))
            db.execute("DELETE FROM schedules WHERE workflow=?",(wid,))
            db.execute("DELETE FROM workflows WHERE id=?",(wid,))
        if kind=="projects":
            db.execute("DELETE FROM projects WHERE id=?",(ident,))
    return {"deleted":ident}


def notify(message):
    target=os.getenv("GARDEN_WEBHOOK","http://127.0.0.1:"+str(PORT)+BASE+"/inbox")
    request=Request(target,json.dumps(message).encode(),{"Content-Type":"application/json"})
    with urlopen(request,timeout=10) as response:
        if not 200<=response.status<300:
            raise RuntimeError("Webhook delivery failed")


def enqueue(wid,mode):
    graph,ver,files=one("SELECT graph,version,files FROM workflows JOIN projects ON project=projects.id WHERE workflows.id=?",(wid,))
    graph=json.loads(graph)
    if not any(n["type"]==mode+"_trigger" for n in graph["nodes"]):
        raise ValueError("Matching trigger missing")
    run=uuid.uuid4().hex
    sql("INSERT INTO runs VALUES(?,?,?,'queued',NULL,NULL,?)",(run,wid,ver,time.time()))
    def event(node,status,payload):
        sql("INSERT INTO events(run,node,status,payload,created) VALUES(?,?,?,?,?)",(run,node,status,json.dumps(payload),time.time()))
    def worker():
        try:
            sql("UPDATE runs SET status='running' WHERE id=?",(run,))
            def save_report(report):
                sql("UPDATE runs SET result=? WHERE id=?",(json.dumps(report),run))
            result=execute(graph,read_source(files),event,run,notify,mode,save_report)
            sql("UPDATE runs SET status='success',result=? WHERE id=?",(json.dumps(result),run))
        except Exception as exc:
            sql("UPDATE runs SET status='failed',error=? WHERE id=?",(str(exc)[:200],run))
    POOL.submit(worker)
    return {"run_id":run}


def scheduler():
    while not STOP.wait(1):
        minute=int(time.time()//60)
        for wid,expr,zone in sql("SELECT workflow,expr,zone FROM cron_jobs WHERE last<?",(minute,),True):
            if sql("UPDATE cron_jobs SET last=? WHERE workflow=? AND last<?",(minute,wid,minute)) and due(expr,zone,minute*60):
                try:
                    enqueue(wid,"schedule")
                except (LookupError,ValueError):
                    sql("DELETE FROM cron_jobs WHERE workflow=?",(wid,))
        for wid,minutes,due in sql("SELECT workflow,minutes,next FROM schedules WHERE next<=?",(time.time(),),True):
            if sql("UPDATE schedules SET next=? WHERE workflow=? AND next=?",(time.time()+60*minutes,wid,due)):
                try:
                    enqueue(wid,"schedule")
                except (ValueError,LookupError):
                    sql("DELETE FROM schedules WHERE workflow=?",(wid,))


def dispatch(method,path,body):
    parts=path.strip("/").split("/")
    if parts[0:2]!=["api","v1"]:
        raise LookupError("Use /api/v1")
    p=parts[2:]
    if method=="DELETE" and len(p)==2 and p[0] in ("projects","workflows"):
        return remove_record(p[0],p[1])
    if method=="GET" and p==["settings"]:
        return {"model":os.getenv("AI_MODEL","qwen3:4b"),"channel":"http_webhook","storage":"sqlite"}
    if method=="GET" and p==["findings"]:
        return [{"run_id":run,**item} for run,result in sql("SELECT id,result FROM runs WHERE result IS NOT NULL",fetch=True)
                if json.loads(result) for item in json.loads(result)["submission"]["findings"]]
    if method=="GET" and p==["health"]:
        return {"status":"ok"}
    if method=="GET" and p==["nodes"]:
        return {"types":TYPES,"default_graph":DEFAULT}
    if method=="POST" and p==["projects"]:
        if body.get("repository_url"):
            if body["repository_url"].rstrip("/") != OFFICIAL:
                raise ValueError("Only the organizers' repository URL is allowed")
            with urlopen("https://codeload.github.com/TBagirov/training/zip/refs/heads/main",timeout=30) as response:
                archive=response.read(LIMIT+1)
        else:
            archive=base64.b64decode(body["zip_base64"],validate=True)
        files=unpack(archive)
        ident=uuid.uuid4().hex
        encrypted=source_cipher().encrypt(json.dumps(files).encode())
        sql("INSERT INTO projects VALUES(?,?,?)",(ident,title(body),encrypted))
        return {"id":ident,"files":len(files)}
    if method=="GET" and p==["projects"]:
        return [dict(id=i,name=n) for i,n in sql("SELECT id,name FROM projects",fetch=True)]
    if method=="GET" and len(p)==2 and p[0]=="projects":
        name,files=one("SELECT name,files FROM projects WHERE id=?",(p[1],))
        return {"id":p[1],"name":name,"files":list(read_source(files))}
    if method=="PUT" and len(p)==2 and p[0]=="projects":
        if not sql("UPDATE projects SET name=? WHERE id=?",(title(body),p[1])):
            raise LookupError("Unknown project")
        return {"id":p[1]}
    if method=="POST" and p==["workflows","validate"]:
        return {"order":validate(body["graph"])}
    if method=="POST" and p==["workflows"]:
        return save_workflow(body)
    if method=="GET" and p==["workflows"]:
        return [dict(id=i,project_id=j,name=n,version=v) for i,j,n,v in sql("SELECT id,project,name,version FROM workflows",fetch=True)]
    if len(p)>=2 and p[0]=="workflows":
        wid=p[1]
        if len(p)==2 and method=="PUT":
            return save_workflow(body,wid)
        if len(p)==2 and method=="GET":
            name,graph,v=one("SELECT name,graph,version FROM workflows WHERE id=?",(wid,))
            return {"id":wid,"name":name,"graph":json.loads(graph),"version":v}
        if p[2:]==["validate"] and method=="POST":
            return {"order":validate(json.loads(one("SELECT graph FROM workflows WHERE id=?",(wid,))[0]))}
        if p[2:]==["versions"] and method=="GET":
            return [dict(version=v,graph=json.loads(g)) for v,g in sql("SELECT version,graph FROM versions WHERE id=? ORDER BY version",(wid,),True)]
        if p[2:]==["runs"] and method=="POST":
            return enqueue(wid,"manual")
        if p[2:]==["schedule"] and method=="PUT":
            minutes=body.get("minutes")
            graph=json.loads(one("SELECT graph FROM workflows WHERE id=?",(wid,))[0])
            expr=body.get("cron")
            zone=body.get("timezone","UTC")
            if expr is not None:
                parse_cron(expr,zone)
            if minutes is not None and (type(minutes)!=int or not 1<=minutes<=525600 or expr is not None):
                raise ValueError("Choose cron or a positive minute interval")
            if (minutes is not None or expr is not None) and not any(n["type"]=="schedule_trigger" for n in graph["nodes"]):
                raise ValueError("Schedule trigger missing")
            with closing(conn()) as db, db:
                db.execute("DELETE FROM schedules WHERE workflow=?",(wid,))
                db.execute("DELETE FROM cron_jobs WHERE workflow=?",(wid,))
                if minutes is not None:
                    db.execute("INSERT INTO schedules VALUES(?,?,?)",(wid,minutes,time.time()+60*minutes))
                if expr is not None:
                    db.execute("INSERT INTO cron_jobs VALUES(?,?,?,?)",(wid,expr,zone,int(time.time()//60)))
            return {"minutes":minutes,"cron":expr,"timezone":zone}
    if method=="GET" and p==["runs"]:
        return [dict(id=i,workflow_id=w,version=v,status=s,created=t) for i,w,v,s,t in sql("SELECT id,workflow,version,status,created FROM runs ORDER BY created DESC",fetch=True)]
    if method=="GET" and len(p)>=2 and p[0]=="runs":
        state,raw,err=one("SELECT status,result,error FROM runs WHERE id=?",(p[1],))
        result=json.loads(raw) if raw else None
        if p[2:]==["report"]:
            if not result:
                raise LookupError("Report not available")
            return result
        if p[2:]==["events"]:
            return [dict(seq=i,node=n,status=s,output=json.loads(d),time=t) for i,n,s,d,t in sql("SELECT seq,node,status,payload,created FROM events WHERE run=? ORDER BY seq",(p[1],),True)]
        if len(p)==2:
            return {"id":p[1],"status":state,"error":err}
    if method=="POST" and p==["inbox"]:
        msg={"run_id":str(body["run_id"])[:64],"count":int(body["count"]),"report_path":str(body["report_path"])[:160]}
        sql("INSERT INTO inbox(message) VALUES(?)",(json.dumps(msg),))
        return {"delivered":True}
    if method=="GET" and p==["inbox"]:
        return [json.loads(m) for m, in sql("SELECT message FROM inbox ORDER BY id DESC",fetch=True)]
    raise LookupError("Unknown endpoint")


class Handler(BaseHTTPRequestHandler):
    def handle_request(self):
        path=urlsplit(self.path).path
        origin=self.headers.get("Origin")
        try:
            if self.headers.get("Host","").split(":")[0] not in ("localhost","127.0.0.1"):
                raise PermissionError("Local service")
            if origin and origin not in ("http://localhost:5173","http://127.0.0.1:5173","http://localhost:"+str(PORT),"http://127.0.0.1:"+str(PORT)):
                raise PermissionError("Origin denied")
            self.cors=origin
            if self.command=="OPTIONS":
                return self.reply(204,b"","text/plain")
            body={}
            if self.command in ("PUT","POST"):
                length=int(self.headers.get("Content-Length","0"))
                if not 0<=length<=18*1024*1024:
                    raise ValueError("Request too large")
                if length and self.headers.get_content_type()!="application/json":
                    raise ValueError("Use application/json")
                body=json.loads(self.rfile.read(length)) if length else {}
                if not isinstance(body,dict):
                    raise ValueError("Expected JSON object")
            if self.command=="GET" and path.endswith("/events") and "text/event-stream" in self.headers.get("Accept",""):
                return self.stream(path)
            if self.command=="GET" and path.endswith("/report.html"):
                report=dispatch("GET",path[:-5],{})
                return self.reply(200,display_report(report).encode(),"text/html; charset=utf-8")
            if self.command=="GET" and path.endswith("/submission.json"):
                value=dispatch("GET",path.rsplit("/",1)[0]+"/report",{})["submission"]
            else:
                value=dispatch(self.command,path,body)
            return self.reply(200,json.dumps(value,ensure_ascii=False).encode(),"application/json; charset=utf-8")
        except (BrokenPipeError,ConnectionResetError):
            return
        except Exception as exc:
            status=403 if isinstance(exc,PermissionError) else 404 if isinstance(exc,LookupError) and not isinstance(exc,KeyError) else 400
            self.reply(status,json.dumps({"error":str(exc)[:240]}).encode(),"application/json")

    def reply(self,status,data,mime):
        self.send_response(status)
        self.send_header("Content-Type",mime)
        self.send_header("Content-Length",str(len(data)))
        if getattr(self,"cors",None):
            self.send_header("Access-Control-Allow-Origin",self.cors)
            self.send_header("Access-Control-Allow-Methods","GET,POST,PUT,DELETE,OPTIONS")
            self.send_header("Access-Control-Allow-Headers","Content-Type, Last-Event-ID")
        self.end_headers()
        self.wfile.write(data)

    def stream(self,path):
        runpath=path.rsplit("/",1)[0]
        dispatch("GET",runpath,{})
        last=int(self.headers.get("Last-Event-ID","0"))
        self.send_response(200)
        self.send_header("Content-Type","text/event-stream")
        self.send_header("Cache-Control","no-cache")
        if self.cors:
            self.send_header("Access-Control-Allow-Origin",self.cors)
        self.end_headers()
        while not STOP.is_set():
            terminal=dispatch("GET",runpath,{})["status"] in ("success","failed")
            for e in dispatch("GET",path,{}):
                if e["seq"]>last:
                    last=e["seq"]
                    self.wfile.write(f"id: {last}\ndata: {json.dumps(e)}\n\n".encode())
            self.wfile.flush()
            if terminal:
                break
            time.sleep(.4)

    do_GET=do_POST=do_PUT=do_DELETE=do_OPTIONS=handle_request


if __name__=="__main__":
    with ThreadingHTTPServer(("127.0.0.1",PORT),Handler) as service:
        init()
        threading.Thread(target=scheduler,daemon=True).start()
        print(f"Cyber Garden API: http://127.0.0.1:{PORT}{BASE}/health",flush=True)
        try:
            service.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            STOP.set()
