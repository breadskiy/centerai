from graphlib import TopologicalSorter, CycleError
import json
import os
import re
from urllib.request import Request, urlopen

from ai_report import read_findings, generate_report, OllamaProvider, OpenAICompatibleProvider
from pydantic_core import SchemaValidator, SchemaError, core_schema
from analysis_nodes import SCANNERS, SubmissionReportExporter

TYPES = ["manual_trigger","schedule_trigger","repository_source",*SCANNERS,"severity_filter","regex_filter","if_else","ai_analysis","report","notification"]
DEFAULT = {"nodes":[{"id":t,"type":t} for t in ["manual_trigger","repository_source",*SCANNERS,"ai_analysis","report","notification"]],
           "edges":[{"source":"manual_trigger","target":"repository_source"}]+
                   [{"source":"repository_source","target":t} for t in SCANNERS]+
                   [{"source":t,"target":"ai_analysis"} for t in SCANNERS]+
                   [{"source":"ai_analysis","target":"report"},{"source":"report","target":"notification"}]}


def validate(graph):
    nodes, edges = graph["nodes"], graph["edges"]
    if not isinstance(nodes,list) or not 1<=len(nodes)<=64 or not isinstance(edges,list) or len(edges)>256:
        raise ValueError("Invalid graph size")
    types = {}
    for n in nodes:
        node, kind = n["id"], n["type"]
        if not re.fullmatch(r"[\w-]{1,64}",node) or node in types or kind not in TYPES:
            raise ValueError("Invalid or duplicate node")
        types[node] = kind
        cfg = n.get("config",{})
        if not isinstance(cfg,dict):
            raise ValueError("Expected node config")
        if kind=="regex_filter":
            pat = cfg.get("pattern","")
            if not isinstance(pat,str) or not 1<=len(pat)<=256:
                raise ValueError("Expected regex of 1-256 characters")
            try:
                SchemaValidator(core_schema.str_schema(pattern=pat,regex_engine="rust-regex"))
            except SchemaError as exc:
                raise ValueError("Invalid or unsupported regex") from exc
        if kind in ("if_else","severity_filter") and cfg.get("severity","HIGH") not in ("CRITICAL","HIGH","MEDIUM","LOW","INFO"):
            raise ValueError("Invalid severity")
        if kind=="if_else" and (type(cfg.get("min_count",1))!=int or cfg.get("min_count",1)<0):
            raise ValueError("Invalid min_count")
    incoming = {key:[] for key in types}
    for e in edges:
        src,dst=e["source"],e["target"]
        if src not in types or dst not in types or (types[src]=="if_else" and e.get("branch") not in ("true","false")):
            raise ValueError("Invalid graph edge")
        if types[src]!="if_else" and "branch" in e:
            raise ValueError("Branch labels belong to if_else")
        incoming[dst].append(e)
    for node,kind in types.items():
        if bool(incoming[node]) == (kind in ("manual_trigger","schedule_trigger")):
            raise ValueError("Only triggers may start a graph")
    try:
        return list(TopologicalSorter({n:{e["source"] for e in ee} for n,ee in incoming.items()}).static_order())
    except CycleError as error:
        raise ValueError("Cycle in workflow") from error


def execute(graph,files,event,run_id,notify,mode,save_report=None):
    order=validate(graph)
    nodes={n["id"]:n for n in graph["nodes"]}
    states={}
    outputs={}
    final=None
    for ident in order:
        n=nodes[ident]
        kind=n["type"]
        cfg=n.get("config",{})
        edges=[e for e in graph["edges"] if e["target"]==ident]
        active=[e["source"] for e in edges if states.get(e["source"])=="success" and
                ("branch" not in e or outputs[e["source"]].get("branch")==e["branch"])]
        if (edges and not active) or (kind.endswith("_trigger") and kind!=mode+"_trigger"):
            states[ident]="skipped"
            event(ident,"skipped",{})
            continue
        event(ident,"running",{})
        try:
            previous=[outputs[k] for k in active]
            unique={json.dumps(v,sort_keys=True):v for p in previous for v in p["rows"]}
            rows=list(unique.values())
            out={"rows":rows,"source":any(p.get("source") for p in previous)}
            if kind=="repository_source":
                out["source"]=True
            elif kind in SCANNERS:
                if not out["source"]:
                    raise ValueError("Connect repository_source before a scanner")
                out["rows"]=rows+SCANNERS[kind](files)
            elif kind=="severity_filter":
                out["rows"]=[v for v in rows if v["severity"]==cfg.get("severity","HIGH")]
            elif kind=="regex_filter":
                pattern=SchemaValidator(core_schema.str_schema(pattern=cfg["pattern"],regex_engine="rust-regex"))
                out["rows"]=[v for v in rows if pattern.isinstance_python(v["path"])]
            elif kind=="if_else":
                count=sum(v["severity"]==cfg.get("severity","HIGH") for v in rows)
                out["branch"]="true" if count>=cfg.get("min_count",1) else "false"
            elif kind=="ai_analysis":
                if os.getenv("AI_PROVIDER","ollama")=="openai-compatible":
                    provider=OpenAICompatibleProvider(os.environ["AI_MODEL"],os.environ["AI_BASE_URL"],os.getenv("AI_API_KEY"))
                else:
                    provider=OllamaProvider(os.getenv("AI_MODEL","qwen3:4b"),os.getenv("AI_BASE_URL","http://127.0.0.1:11434"))
                out["ai"]=generate_report(read_findings({"findings":rows}),provider)
            elif kind=="report":
                ai=next((p["ai"] for p in previous if "ai" in p),None)
                if ai is not None and ai["findings"] != [f.model_dump(mode="json") for f in read_findings({"findings":rows})]:
                    raise ValueError("Report needs matching AI input")
                final={"submission":SubmissionReportExporter.export(rows),"ai":ai}
                if save_report:
                    save_report(final)
                out["report"]=final
            elif kind=="notification":
                report=next((p["report"] for p in previous if "report" in p),None)
                if report is None:
                    raise ValueError("Connect report before notification")
                notify({"run_id":run_id,"count":len(report["submission"]["findings"]),"report_path":"/api/v1/runs/"+run_id+"/report"})
            if kind in ("if_else","severity_filter","regex_filter") and len(previous)==1 and out["rows"]==rows:
                for field in ("ai","report"):
                    if field in previous[0]:
                        out[field]=previous[0][field]
            states[ident]="success"
            outputs[ident]=out
            event(ident,"success",{"findings":SubmissionReportExporter.export(out["rows"])["findings"],
                                  **{k:v for k,v in out.items() if k=="branch"},
                                  **({"ai_status":out["ai"]["status"]} if "ai" in out else {})})
        except Exception as exc:
            event(ident,"failed",{"error":str(exc)[:200]})
            raise
    return final
