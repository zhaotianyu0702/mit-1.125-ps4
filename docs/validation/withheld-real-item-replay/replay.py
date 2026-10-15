#!/usr/bin/env python3
"""Replay real retained eligible records through a disposable evidence store only."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[3]
OUTPUT=Path(__file__).resolve().parent

def records(path):
    out=[]
    for n,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
        if not line.strip(): continue
        row=json.loads(line)
        if not isinstance(row,dict): raise ValueError(f'{path}:{n} must contain JSON objects')
        out.append(row)
    return out

def jsonl(rows):
    return ''.join(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n' for row in rows)

def invoke(argv,cwd,env,input_text=None):
    p=subprocess.run(argv,cwd=cwd,env=env,input=input_text,text=True,capture_output=True,timeout=60)
    if p.returncode:
        raise RuntimeError(f'Command failed ({p.returncode}): {argv[0]} {argv[1:]}; {p.stderr.strip()}')
    return p.stdout

def counter(rows):
    return {name:sum(r.get('change')==name for r in rows) for name in ('new','changed','unchanged')}

def copy_runtime(temp_root):
    for rel in ('data/store.py','data/store.sh','lib/common.py',
                'processing/filter_items.py','processing/filter_items.sh'):
        target=temp_root/rel; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/rel,target)

def run(source_run,item_id=None):
    source=source_run.resolve()
    meta=json.loads((source/'run.json').read_text(encoding='utf-8'))
    if meta.get('mode')!='live': raise ValueError('Source evidence must come from a recorded live run')
    as_of=meta.get('as_of_date')
    dt.date.fromisoformat(as_of)
    eligible=records(source/'eligible.jsonl')
    decisions=records(source/'decisions.jsonl') if (source/'decisions.jsonl').is_file() else []
    by_decision={(d.get('item_id'),d.get('version_id')):d for d in decisions}
    eligible_keys={(x.get('item_id'),x.get('version_id')) for x in eligible}
    if item_id is None:
        # Prefer an accepted item whose current observation was unchanged in this live run.
        changes=records(source/'changes.jsonl') if (source/'changes.jsonl').is_file() else []
        change_map={x.get('item_id'):x.get('change') for x in changes}
        chosen=next((x for x in eligible if by_decision.get((x.get('item_id'),x.get('version_id')),{}).get('decision')=='accept'
                     and change_map.get(x.get('item_id'))=='unchanged'),None)
        if chosen is None: raise ValueError('No accepted unchanged eligible item is available to withhold')
        item_id=chosen['item_id']
    matching=[x for x in eligible if x.get('item_id')==item_id]
    if len(matching)!=1: raise ValueError(f'Expected exactly one eligible item {item_id!r}, found {len(matching)}')
    withheld=matching[0]
    decision=by_decision.get((withheld.get('item_id'),withheld.get('version_id')))
    if decisions and decision is None: raise ValueError('Selected record has no same-version decision in the live run')
    if len(eligible)<2: raise ValueError('Need at least two eligible records for withheld-item demonstration')
    ids=[x.get('item_id') for x in eligible]
    if len(set(ids))!=len(ids): raise ValueError('Live eligible input contains duplicate item IDs; this replay expects distinct records')
    baseline=[x for x in eligible if x['item_id']!=item_id]
    now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    replay_meta={'run_id':'withheld-real-item-replay','started_at':now,'as_of_date':as_of,
                 'mode':'replay','previous_run_id':meta.get('run_id'),'source_live_run_id':meta.get('run_id')}

    with tempfile.TemporaryDirectory(prefix='ps4-withheld-replay-') as temp:
        temp_root=Path(temp)/'project'; temp_root.mkdir()
        copy_runtime(temp_root)
        replay_dir=temp_root/'runs'/'withheld-real-item-replay'
        replay_dir.mkdir(parents=True)
        (replay_dir/'run.json').write_text(json.dumps(replay_meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        env=dict(os.environ,PS4_RUN_DIR='runs/withheld-real-item-replay',PYTHONDONTWRITEBYTECODE='1')
        invoke(['bash','data/store.sh','init'],temp_root,env)
        first_stdout=invoke(['bash','data/store.sh','upsert','runs/withheld-real-item-replay'],temp_root,env,jsonl(baseline))
        first=[json.loads(x) for x in first_stdout.splitlines()]
        introduce_stdout=invoke(['bash','data/store.sh','upsert','runs/withheld-real-item-replay'],temp_root,env,jsonl(eligible))
        introduce=[json.loads(x) for x in introduce_stdout.splitlines()]
        replay_stdout=invoke(['bash','data/store.sh','upsert','runs/withheld-real-item-replay'],temp_root,env,jsonl(eligible))
        exact=[json.loads(x) for x in replay_stdout.splitlines()]
        corpus_stdout=invoke(['bash','data/store.sh','list'],temp_root,env)
        corpus=[json.loads(x) for x in corpus_stdout.splitlines()]
        filtered_stdout=invoke(['bash','processing/filter_items.sh','runs/withheld-real-item-replay'],temp_root,env,jsonl(corpus))
        filtered=[json.loads(x) for x in filtered_stdout.splitlines()]
        excluded=records(replay_dir/'exclusions.jsonl')
        logs=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((replay_dir/'logs').glob('*.json'))]

        expected_intro=[{'item_id':x['item_id'],'version_id':x['version_id'],
                         'change':'new' if x['item_id']==item_id else 'unchanged'} for x in eligible]
        checks={
            'baseline_has_35_or_n_minus_one_new':counter(first)=={'new':len(baseline),'changed':0,'unchanged':0},
            'introduction_has_one_new_and_rest_unchanged':introduce==expected_intro,
            'exact_replay_has_only_unchanged':len(exact)==len(eligible) and all(x['change']=='unchanged' for x in exact),
            'no_duplicate_observations_in_each_input':all(len({x['item_id'] for x in batch})==len(batch) for batch in (baseline,eligible,eligible)),
            'corpus_contains_each_real_record_once':len(corpus)==len(eligible) and {(x['item_id'],x['version_id']) for x in corpus}==eligible_keys,
            'withheld_record_is_date_eligible':any(x['item_id']==item_id and x['version_id']==withheld['version_id'] for x in filtered),
            'filter_preserves_all_eligible_records':len(filtered)==len(eligible) and not excluded,
            'replay_metadata_is_labeled':replay_meta['mode']=='replay' and replay_meta['as_of_date']==as_of,
        }
        if len(eligible)==36:
            checks['thirty_five_unchanged_plus_one_new']=(counter(introduce)=={'new':1,'changed':0,'unchanged':35})
            checks['thirty_six_unchanged_on_exact_replay']=(counter(exact)=={'new':0,'changed':0,'unchanged':36})
        result={'status':'passed' if all(checks.values()) else 'failed','mode':'replay',
                'executed_at':now,'source_live_run_id':meta.get('run_id'),'as_of_date':as_of,
                'replay_run':replay_meta,'selected_item':{k:withheld.get(k) for k in
                    ('item_id','version_id','title','url','published_at','publisher_id','kind')},
                'actual_live_decision':decision,'counts':{'eligible_source':len(eligible),'baseline':len(baseline),
                    'baseline_changes':counter(first),'introduction_changes':counter(introduce),
                    'exact_replay_changes':counter(exact),'duplicate_observations':0,
                    'filter_eligible':len(filtered),'excluded':len(excluded)},
                'checks':checks,'logs':logs,'note':'Fictional inputs were not used; the one withheld record is an exact eligible record from the named live run. This demonstration uses an isolated temporary SQLite store and is not a live run.'}
        OUTPUT.mkdir(parents=True,exist_ok=True)
        (OUTPUT/'baseline_changes.jsonl').write_text(jsonl(first),encoding='utf-8')
        (OUTPUT/'introduction_changes.jsonl').write_text(jsonl(introduce),encoding='utf-8')
        (OUTPUT/'exact_replay_changes.jsonl').write_text(jsonl(exact),encoding='utf-8')
        (OUTPUT/'corpus.jsonl').write_text(jsonl(corpus),encoding='utf-8')
        (OUTPUT/'eligible.jsonl').write_text(jsonl(filtered),encoding='utf-8')
        (OUTPUT/'exclusions.jsonl').write_text(jsonl(excluded),encoding='utf-8')
        logdir=OUTPUT/'logs'; logdir.mkdir(exist_ok=True)
        for p in sorted((replay_dir/'logs').glob('*.json')): shutil.copy2(p,logdir/p.name)
        (OUTPUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('live_run',type=Path,help='recorded live run with eligible.jsonl and decisions.jsonl')
    parser.add_argument('--item-id',help='eligible item to withhold; defaults to first accepted unchanged eligible item')
    args=parser.parse_args()
    try:
        result=run(args.live_run,args.item_id)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['status']=='passed' else 1
    except (OSError,ValueError,KeyError,RuntimeError,json.JSONDecodeError) as exc:
        print(f'withheld replay failed: {exc}',file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
