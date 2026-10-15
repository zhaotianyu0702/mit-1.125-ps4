#!/usr/bin/env python3
"""Apply the fixed inclusive 30-calendar-date UTC freshness window."""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from common import BadInput, stage_main, read_jsonl, atomic_write, emit

def utc_day(value):
    if not isinstance(value,str) or not value: raise ValueError('missing date')
    # A date-only ISO value represents that UTC calendar date.
    if len(value)==10:
        return dt.date.fromisoformat(value)
    stamp=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None: raise ValueError('timestamp needs timezone')
    return stamp.astimezone(dt.timezone.utc).date()

def run_filter(run,receipt):
    try:
        meta=json.loads((run/'run.json').read_text())
        asof=dt.date.fromisoformat(meta['as_of_date'])
    except (OSError,ValueError,KeyError,TypeError) as e:
        raise BadInput(f'run.json requires valid as_of_date (YYYY-MM-DD): {e}')
    items=read_jsonl(sys.stdin); eligible=[]; exclusions=[]
    start=asof-dt.timedelta(days=29)
    for i,item in enumerate(items,1):
        if not isinstance(item.get('item_id'),str) or not item['item_id']:
            raise BadInput(f'Item line {i} requires item_id')
        raw=item.get('published_at')
        if raw is None:
            reason='unknown_date'
        else:
            try: day=utc_day(raw)
            except (ValueError,TypeError,OverflowError): reason='invalid_date'
            else:
                if day>asof: reason='future_date'
                elif day<start: reason='outside_window'
                else: reason=None
        if reason is None: eligible.append(item)
        else: exclusions.append({'item_id':item['item_id'],'version_id':item.get('version_id'),'reason':reason,'detail':f'published_at={raw!r}; eligible UTC dates {start.isoformat()} through {asof.isoformat()} inclusive'})
    receipt.input_count=len(items); receipt.output_count=len(eligible)
    receipt.extra.update(window_start=start.isoformat(),window_end=asof.isoformat(),excluded_count=len(exclusions))
    path=run/'exclusions.jsonl'; path.parent.mkdir(parents=True,exist_ok=True)
    atomic_write(path,''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in exclusions))
    emit(eligible)
    return 0

if __name__=='__main__': raise SystemExit(stage_main('processing/filter_items',run_filter))
