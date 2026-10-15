#!/usr/bin/env python3
"""SQLite evidence store. Supplied version IDs are opaque and retrieval time is observational."""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'evidence' / 'store.sqlite3'
sys.path.insert(0, str(ROOT / 'lib'))
from common import BadInput, Receipt, read_jsonl, emit  # noqa: E402

REQUIRED = ('item_id','source_id','publisher_id','kind','title','url','published_at',
            'retrieved_at','media_url','version_id','text_path','segments_path')

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('''CREATE TABLE IF NOT EXISTS versions (
      item_id TEXT NOT NULL, version_id TEXT NOT NULL, record TEXT NOT NULL,
      PRIMARY KEY(item_id, version_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS observations (
      item_id TEXT NOT NULL, version_id TEXT NOT NULL, run_id TEXT NOT NULL,
      PRIMARY KEY(item_id, version_id, run_id),
      FOREIGN KEY(item_id,version_id) REFERENCES versions(item_id,version_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS current_versions (
      item_id TEXT PRIMARY KEY, version_id TEXT NOT NULL,
      FOREIGN KEY(item_id,version_id) REFERENCES versions(item_id,version_id))''')
    # Migrate stores created before the explicit current-version pointer existed.
    db.execute('''INSERT OR IGNORE INTO current_versions(item_id,version_id)
      SELECT v.item_id,v.version_id FROM versions v JOIN
      (SELECT item_id,MAX(rowid) AS r FROM versions GROUP BY item_id) x ON x.r=v.rowid''')
    db.commit()
    return db

def validate(records):
    for n, r in enumerate(records, 1):
        missing = [k for k in REQUIRED if k not in r]
        if missing: raise BadInput(f'Item line {n} missing fields: {", ".join(missing)}')
        for k in ('item_id','source_id','publisher_id','kind','title','url','version_id'):
            if not isinstance(r[k], str) or not r[k]: raise BadInput(f'Item line {n}: {k} must be a nonempty string')
        if r['kind'] not in ('feed','youtube','podcast'): raise BadInput(f'Item line {n}: kind must be feed, youtube, or podcast')
        for k in ('published_at','retrieved_at','media_url','text_path','segments_path'):
            if r[k] is not None and not isinstance(r[k], str): raise BadInput(f'Item line {n}: {k} must be a string or null')
        if not r['text_path']: raise BadInput(f'Item line {n}: text_path must be a nonempty path')
        if r['kind'] in ('youtube','podcast') and not r['segments_path']:
            raise BadInput(f'Item line {n}: {r["kind"]} items require segments_path')
        if r['kind']=='feed' and r['segments_path'] is not None:
            raise BadInput(f'Item line {n}: feed items must have segments_path null')

def semantic_record(record):
    # Raw download paths and HTTP validators may change while normalized evidence is identical.
    observational = ('retrieved_at', 'source_id', 'media_path', 'transcript_media_path',
                     'etag', 'last_modified', 'media_etag', 'media_last_modified',
                     'publication_precision', 'source_date_field')
    return {k:v for k,v in record.items() if k not in observational}

def receipt_for(command, run=None):
    return Receipt(run or Path(os.environ.get('PS4_RUN_DIR', ROOT/'runs'/'store-operations')), f'data/store:{command}')

def main():
    if len(sys.argv) < 2:
        print('Usage: store.py init | upsert RUN_DIR | list | get ITEM_ID [VERSION_ID]', file=sys.stderr); return 2
    cmd=sys.argv[1]
    if cmd not in ('init','upsert','list','get') or (cmd=='upsert' and len(sys.argv)!=3) or (cmd=='get' and len(sys.argv) not in (3,4)) or (cmd in ('init','list') and len(sys.argv)!=2):
        print('Invalid store arguments', file=sys.stderr); return 2
    run = None
    if cmd=='upsert':
        try:
            run=(ROOT / sys.argv[2]).resolve()
            if ROOT not in run.parents or not (run/'run.json').is_file(): raise BadInput('RUN_DIR must be inside repository and contain run.json')
            records=read_jsonl(sys.stdin); validate(records)
            run_id=json.loads((run/'run.json').read_text()).get('run_id')
            if not isinstance(run_id,str) or not run_id: raise BadInput('run.json must contain run_id')
        except (BadInput, OSError, ValueError) as e:
            print(str(e),file=sys.stderr)
            # A caller may supply a run directory for logging even when ingestion is invalid.
            logrun=Path(os.environ.get('PS4_RUN_DIR', ROOT/'runs'/'store-operations'))
            rec=Receipt(logrun,'data/store:upsert'); rec.input_count=None; rec.error(str(e)); rec.save(2)
            return 2
    rec = receipt_for(cmd, run)
    try:
        db=connect()
        if cmd=='init': db.close(); rec.input_count=0; rec.output_count=0; rec.save(0); return 0
        if cmd=='upsert':
            # Validate the entire batch before opening the write transaction.
            output=[]
            with db:
                seen={}
                batch_versions=set()
                for item in records:
                    iid,vid=item['item_id'],item['version_id']
                    current=seen.get(iid)
                    if current is None:
                        row=db.execute('SELECT version_id FROM current_versions WHERE item_id=?',(iid,)).fetchone()
                    else: row=(current,)
                    existing=db.execute('SELECT record FROM versions WHERE item_id=? AND version_id=?',(iid,vid)).fetchone()
                    if existing and semantic_record(json.loads(existing[0])) != semantic_record(item):
                        raise BadInput(f'Version ID collision with different evidence: {iid} / {vid}')
                    exists=existing is not None
                    key=(iid,vid)
                    repeated=key in batch_versions
                    change='unchanged' if repeated else ('new' if row is None else ('unchanged' if row[0]==vid else 'changed'))
                    if not exists:
                        db.execute('INSERT INTO versions VALUES(?,?,?)',(iid,vid,json.dumps(item,ensure_ascii=False,separators=(',',':'))))
                    db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?)',(iid,vid,run_id))
                    db.execute('INSERT INTO current_versions VALUES(?,?) ON CONFLICT(item_id) DO UPDATE SET version_id=excluded.version_id',(iid,vid))
                    output.append({'item_id':iid,'version_id':vid,'change':change})
                    seen[iid]=vid
                    batch_versions.add(key)
            rec.input_count=len(records); rec.output_count=len(output); rec.save(0); emit(output); db.close(); return 0
        if cmd=='list':
            rows=db.execute('''SELECT v.record FROM versions v JOIN current_versions c ON c.item_id=v.item_id AND c.version_id=v.version_id ORDER BY v.rowid''').fetchall()
        else:
            params=(sys.argv[2],) if len(sys.argv)==3 else (sys.argv[2],sys.argv[3])
            if len(params) == 1:
                q='SELECT v.record FROM versions v JOIN current_versions c ON c.item_id=v.item_id AND c.version_id=v.version_id WHERE v.item_id=?'
            else:
                q='SELECT record FROM versions WHERE item_id=? AND version_id=?'
            rows=db.execute(q,params).fetchall()
        db.close()
        if not rows and cmd=='get':
            rec.error('Requested evidence item/version was not found'); rec.input_count=0; rec.output_count=0; rec.save(1); return 1
        for row in rows: print(row[0])
        rec.input_count=0; rec.output_count=len(rows); rec.save(0)
        return 0
    except sqlite3.Error as e:
        message=f'Store failure: {e}'
        rec.error(message); rec.save(1); return 1
    except BadInput as e:
        rec.error(str(e)); rec.save(2); return 2

if __name__=='__main__': raise SystemExit(main())
