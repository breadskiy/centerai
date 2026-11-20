"""Submit a harmless synthetic dependency manifest to the running local API."""
import base64
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

API="http://127.0.0.1:"+os.getenv("GARDEN_PORT","8765")+"/api/v1"


def api(path,body=None):
    data=json.dumps(body).encode() if body is not None else None
    with urlopen(Request(API+path,data,{"Content-Type":"application/json"}),timeout=45) as response:
        return json.load(response)


def main():
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w") as archive:
        archive.writestr("build.gradle.kts",'dependencies { implementation("org.jsoup:jsoup:1.14.1") }\n')
    project=api("/projects",{"name":"Local API demo","zip_base64":base64.b64encode(buffer.getvalue()).decode()})
    graph=api("/nodes")["default_graph"]
    workflow=api("/workflows",{"name":"Static checks and local AI","project_id":project["id"],"graph":graph})
    rid=api("/workflows/"+workflow["id"]+"/runs",{})["run_id"]
    print("Run:",rid,flush=True)
    for _ in range(400):
        run=api("/runs/"+rid)
        if run["status"]=="failed":
            raise RuntimeError(run["error"])
        if run["status"]=="success":
            report=api("/runs/"+rid+"/report")
            print("AI:",report["ai"]["status"],"Findings:",len(report["submission"]["findings"]))
            print(API+"/runs/"+rid+"/report.html")
            return
        time.sleep(1)
    raise TimeoutError("Run is still active: "+rid)


if __name__=="__main__":
    main()
