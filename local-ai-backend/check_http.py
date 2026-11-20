"""Exercise a running service with the organizer's local educational fixture."""
import base64
import io
import sys
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen
from demo import api, API


def main():
    root=Path(sys.argv[1])
    data=io.BytesIO()
    with zipfile.ZipFile(data,"w",zipfile.ZIP_DEFLATED) as z:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in (".kt",".kts",".lockfile",".yml",".yaml",".properties"):
                z.write(path,path.relative_to(root))
    project=api("/projects",{"name":"Official fixture","zip_base64":base64.b64encode(data.getvalue()).decode()})
    graph=api("/nodes")["default_graph"]
    graph["nodes"]=[n for n in graph["nodes"] if n["id"]!="ai_analysis"]
    for edge in graph["edges"]:
        if edge["target"]=="ai_analysis":
            edge["target"]="report"
    graph["edges"]=[e for e in graph["edges"] if e["source"]!="ai_analysis"]
    flow=api("/workflows",{"project_id":project["id"],"name":"Official static checks","graph":graph})
    rid=api("/workflows/"+flow["id"]+"/runs",{})["run_id"]
    base="/runs/"+rid
    with urlopen(Request(API+base+"/events",headers={"Accept":"text/event-stream"}),timeout=45) as response:
        stream=response.read().decode()
    assert '"status": "success"' in stream
    assert api(base)["status"]=="success"
    rows=api(base+"/submission.json")["findings"]
    assert len(rows)==15
    assert all("fixedVersions" not in row for row in rows)
    assert any(msg["run_id"]==rid and msg["count"]==15 for msg in api("/inbox"))
    with urlopen(API+base+"/report.html") as response:
        assert "build.gradle.kts" in response.read().decode()
    print("PASS: official ZIP -> 3 scanners -> SSE -> 15 exported findings -> HTML -> delivered webhook",flush=True)


if __name__=="__main__":
    main()
