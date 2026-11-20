"""Five-field cron with time zones, lists, steps and ranges."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re


def cron_values(field,low,high):
    result=set()
    for piece in field.split(","):
        m=re.fullmatch(r'(\*|\d+(?:-\d+)?)(?:/([1-9]\d*))?',piece)
        if not m:
            raise ValueError("Invalid cron expression")
        step=int(m[2] or 1)
        if m[1]=="*":
            start,end=low,high
        else:
            numbers=list(map(int,m[1].split("-")))
            start=numbers[0]
            end=numbers[-1] if len(numbers)>1 or not m[2] else high
        if not low<=start<=end<=high:
            raise ValueError("Cron field out of range")
        result.update(range(start,end+1,step))
    return result


def parse_cron(expr,zone):
    fields=expr.split()
    if len(fields)!=5 or len(expr)>120:
        raise ValueError("Expected five cron fields")
    try:
        tz=timezone.utc if zone=="UTC" else ZoneInfo(zone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Unknown timezone; install tzdata or use UTC") from exc
    values=[cron_values(f,*bounds) for f,bounds in zip(fields,[(0,59),(0,23),(1,31),(1,12),(0,7)])]
    return fields,values,tz


def due(expr,zone,timestamp):
    fields,(minute,hour,day,month,weekday),tz=parse_cron(expr,zone)
    dt=datetime.fromtimestamp(timestamp,tz)
    wd=(dt.weekday()+1)%7
    down=wd in weekday or (wd==0 and 7 in weekday)
    dom=dt.day in day
    date_ok=(dom and down) if fields[2].startswith("*") or fields[4].startswith("*") else (dom or down)
    return dt.minute in minute and dt.hour in hour and dt.month in month and date_ok
