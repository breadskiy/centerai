import base64
import io
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import server
from workflow import DEFAULT, validate, execute
from timing import due, parse_cron
from analysis_nodes import sca


def archive(name,text):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w") as z:
        z.writestr(name,text)
    return buf.getvalue()


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=patch.object(server,"ROOT",Path(self.directory.name))
        self.root.start()
        self.addCleanup(self.root.stop)
        server.init()

    def test_zip_and_db(self):
        with self.assertRaises(ValueError):
            server.unpack(archive("../bad.kt",""))
        blob=archive("demo/build.gradle.kts","dependencies {}")
        project=server.dispatch("POST","/api/v1/projects",{"zip_base64":base64.b64encode(blob),"name":"demo"})
        flow=server.save_workflow({"name":"scan","graph":DEFAULT,"project_id":project["id"]})
        self.assertEqual(server.save_workflow({"name":"renamed","graph":DEFAULT},flow["id"])["version"],2)
        server.remove_record("projects",project["id"])
        self.assertEqual(server.dispatch("GET","/api/v1/workflows",{}),[])

    def test_graph_cycle(self):
        with self.assertRaises(ValueError):
            validate({"nodes":[{"id":"a","type":"sca"}],"edges":[{"source":"a","target":"a"}]})

    def test_branch(self):
        nodes=[("m","manual_trigger"),("s","repository_source"),("d","sca"),("c","if_else"),("yes","report"),("no","report")]
        graph={"nodes":[dict(id=k,type=t) for k,t in nodes],
               "edges":[dict(source=k,target=v) for k,v in [("m","s"),("s","d"),("d","c")]]+
                       [dict(source="c",target="yes",branch="true"),dict(source="c",target="no",branch="false")]}
        log=[]
        result=execute(graph,{"build.gradle.kts":""},lambda n,s,o:log.append((n,s)),"run",None,"manual")
        self.assertIn(("yes","skipped"),log)
        self.assertIn(("no","success"),log)
        self.assertEqual(result["submission"],{"findings":[]})

    def test_notification_failure_preserves_report(self):
        p=server.dispatch("POST","/api/v1/projects",{"zip_base64":base64.b64encode(archive("build.gradle.kts","")),"name":"project"})
        w=server.save_workflow({"name":"flow","project_id":p["id"],"graph":DEFAULT})
        with patch.object(server,"notify",side_effect=ConnectionError("receiver unavailable")):
            rid=server.enqueue(w["id"],"manual")["run_id"]
            for _ in range(200):
                state=server.dispatch("GET","/api/v1/runs/"+rid,{})
                if state["status"]=="failed":
                    break
                time.sleep(.02)
            self.assertEqual(state["status"],"failed")
        self.assertEqual(server.dispatch("GET","/api/v1/runs/"+rid+"/report",{})["submission"],{"findings":[]})

    def test_cron(self):
        self.assertTrue(due("0 0 * * 4","UTC",0))
        self.assertFalse(due("1 0 * * 4","UTC",0))
        with self.assertRaises(ValueError):
            parse_cron("60 0 * * *","UTC")

    def test_locked_safe_version(self):
        files={"build.gradle.kts":'implementation("org.jsoup:jsoup:1.14.1")',"gradle.lockfile":"org.jsoup:jsoup:1.20.0=runtimeClasspath"}
        self.assertEqual(sca(files),[])


if __name__=="__main__":
    unittest.main()
