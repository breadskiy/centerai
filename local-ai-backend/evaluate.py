"""Offline quality measurement. The HTTP server never reads the reference file."""
import argparse
import json
from pathlib import Path
from analysis_nodes import SCANNERS


def matches(row,target):
    if row["category"]=="SCA":
        return (target.get("category")=="SCA" and all(row[k]==target.get(k) for k in ("group","artifact","version"))
                and row["advisoryId"] in target.get("advisoryIds",[]))
    return (row["category"]==target.get("category") and row["class"]==target.get("class")
            and any(row["path"]==loc["path"] and loc["line"]<=row["line"]<=loc.get("endLine",loc["line"])
                    for loc in [target,*target.get("alternateLocations",[])]))


def main():
    p=argparse.ArgumentParser()
    p.add_argument("project",type=Path)
    p.add_argument("reference",type=Path)
    args=p.parse_args()
    files={f.relative_to(args.project).as_posix():f.read_text(encoding="utf-8-sig")
           for f in args.project.rglob("*") if f.is_file() and f.suffix in (".kt",".kts",".properties",".lockfile",".yaml",".yml")}
    ref=json.loads(args.reference.read_text(encoding="utf-8-sig"))
    remaining=list(ref["findings"])
    tp=fp=0
    for scanner in SCANNERS.values():
        for row in scanner(files):
            target=next((t for t in remaining if matches(row,t)),None)
            if target:
                tp+=1
                remaining.remove(target)
            else:
                fp+=1
                print("Unmatched:",row["path"],row.get("class",row.get("advisoryId")),row.get("line"))
    fn=len(remaining)
    print(json.dumps(dict(TP=tp,FP=fp,FN=fn,precision=tp/max(1,tp+fp),recall=tp/max(1,tp+fn),
                          F1=2*tp/max(1,2*tp+fp+fn),missed=[t["id"] for t in remaining]),indent=2))


if __name__=="__main__":
    main()
