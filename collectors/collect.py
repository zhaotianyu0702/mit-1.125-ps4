#!/usr/bin/env python3
"""RSS/Atom discovery and yt-dlp metadata collection for PS04."""
import datetime as dt
import email.utils
import hashlib
import json
import os
import time
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from common import BadInput, Receipt, emit, load_json, repo_path  # noqa: E402

TIMEOUT = 20
MAX_FEED_BYTES = 12 * 1024 * 1024

def fetch(url):
    last=None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'PS04ResearchBot/1.0 (+RSS reader)'})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                data=response.read(MAX_FEED_BYTES+1)
                if len(data)>MAX_FEED_BYTES: raise RuntimeError(f'feed exceeds {MAX_FEED_BYTES} byte limit')
                return data, response.geturl()
        except Exception as exc:
            last=exc
            if attempt<2: time.sleep(0.25*(attempt+1))
    raise last

def date_details(raw):
    if not raw: return None
    try:
        raw=raw.strip()
        if re.fullmatch(r'\d{8}',raw):
            value=dt.datetime.strptime(raw,'%Y%m%d').replace(tzinfo=dt.timezone.utc)
            precision='day'
        elif re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw):
            value=dt.datetime.combine(dt.date.fromisoformat(raw),dt.time(),tzinfo=dt.timezone.utc)
            precision='day'
        else:
            try: value=dt.datetime.fromisoformat(raw.replace('Z','+00:00'))
            except ValueError: value=email.utils.parsedate_to_datetime(raw)
            if value.tzinfo is None: return None,None
            precision='timestamp'
        return value.astimezone(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'),precision
    except (ValueError, TypeError, OverflowError): return None,None

def date_value(raw):
    details=date_details(raw)
    return details[0] if details else None

def publication_date(parent):
    # Explicit original publication date wins over edit/update timestamps.
    preferred=('published','pubdate','date')
    for field in preferred:
        for element in parent.iter():
            if local(element)==field and element.text and element.text.strip():
                stamp,precision=date_details(element.text)
                return stamp,precision,element.tag.rsplit('}',1)[-1]
    return None,None,None

def local(el): return el.tag.rsplit('}', 1)[-1].lower()
def text_of(parent, names):
    for el in parent.iter():
        if local(el) in names and el.text and el.text.strip(): return el.text.strip()
    return None

def parse_feed(data, base):
    root = ET.fromstring(data)
    entries = [e for e in root.iter() if local(e) in ('item','entry')]
    out=[]
    for e in entries:
        title=text_of(e, {'title'}) or '(untitled)'
        link=None; enclosure=None; transcript=None; ident=None
        for n in e.iter():
            tag=local(n); href=n.attrib.get('href'); rel=n.attrib.get('rel','alternate').lower()
            if tag=='link':
                mime=n.attrib.get('type','').lower()
                if rel=='enclosure' and mime.startswith('audio/'): enclosure=href or n.attrib.get('url')
                elif rel=='enclosure': pass
                elif rel in ('alternate',''): link=href or (n.text or '').strip() or link
                if 'transcript' in (n.attrib.get('rel','').lower()+' '+n.attrib.get('type','').lower()): transcript=href
            if tag=='enclosure' and n.attrib.get('url') and n.attrib.get('type','').lower().startswith('audio/'): enclosure=n.attrib['url']
            if tag in ('transcript','podcast:transcript'):
                transcript=n.attrib.get('url') or n.attrib.get('href') or transcript
            if tag in ('guid','id') and n.text: ident=n.text.strip()
        if not link: link=ident
        if not link: continue
        published,precision,date_field=publication_date(e)
        out.append({'title':title,'url':urllib.parse.urljoin(base,link),'published_at':published,'publication_precision':precision,'source_date_field':date_field,
                    'media_url':urllib.parse.urljoin(base,enclosure) if enclosure else None,
                    'transcript_url':urllib.parse.urljoin(base,transcript) if transcript else None,
                    'native_id':ident})
    return out

def load_sources(run, kind):
    path=run/'config'/'sources.json'
    srcs=load_json(path)
    if not isinstance(srcs,list): raise BadInput('sources snapshot must be an array')
    selected=[]
    for i,s in enumerate(srcs,1):
        if not isinstance(s,dict): raise BadInput(f'source {i} must be an object')
        if s.get('kind')!=kind: continue
        if not all(isinstance(s.get(k),str) and s[k] for k in ('source_id','publisher_id','url')): raise BadInput(f'{kind} source {i} needs source_id, publisher_id, url')
        limit=s.get('max_items',6)
        if isinstance(limit,bool) or not isinstance(limit,int) or limit<1: raise BadInput(f'{kind} source {i}: max_items must be positive integer')
        selected.append(s)
    return selected

def run_collector(run, receipt, kind):
    sources=load_sources(run,kind); records=[]; failed=False
    receipt.input_count=len(sources)
    for source in sources:
        try:
            limit=source.get('max_items',6)
            if kind in ('feed','podcast'):
                data,final=fetch(source['url']); entries=parse_feed(data,final)
                if not entries: continue
                eligible=[e for e in entries if kind!='podcast' or e.get('media_url')]
                for e in eligible[:limit]:
                    native=e.pop('native_id',None)
                    rid=native or e['url']
                    key='podcast' if kind=='podcast' else 'feed'
                    record=dict(item_id=f'{key}:{hashlib.sha256(rid.encode()).hexdigest()[:24]}',source_id=source['source_id'],publisher_id=source['publisher_id'],kind=kind,retrieved_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'),**e)
                    if source.get('underlying_id'): record['underlying_id']=source['underlying_id']
                    records.append(record)
            else:
                try: p=subprocess.run([os.environ.get('PS4_YTDLP','yt-dlp'),'--dump-single-json','--playlist-end',str(limit),source['url']],capture_output=True,text=True,timeout=60)
                except FileNotFoundError: raise RuntimeError('yt-dlp executable is required for YouTube metadata discovery')
                if p.returncode: raise RuntimeError('yt-dlp metadata discovery failed: '+(p.stderr.strip()[-600:] or f'exit {p.returncode}'))
                meta=json.loads(p.stdout)
                entries=meta.get('entries') if isinstance(meta.get('entries'),list) else [meta]
                for e in entries[:limit]:
                    vid=e.get('id'); page=e.get('webpage_url') or (f"https://www.youtube.com/watch?v={vid}" if vid else None)
                    if not vid or not page: continue
                    raw_date=None; date_field=None
                    for field in ('release_timestamp','release_date','upload_date'):
                        if e.get(field) is not None:
                            raw_date=e[field]; date_field=field; break
                    if isinstance(raw_date,(int,float)):
                        stamp=dt.datetime.fromtimestamp(raw_date,dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'); precision='timestamp'
                    else:
                        details=date_details(raw_date) if raw_date is not None else (None,None)
                        stamp,precision=details
                    record=dict(item_id='youtube:'+vid,source_id=source['source_id'],publisher_id=source['publisher_id'],kind='youtube',title=e.get('title') or '(untitled)',url=page,published_at=stamp,publication_precision=precision,source_date_field=date_field,media_url=None,native_id=vid,retrieved_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'))
                    if source.get('underlying_id'): record['underlying_id']=source['underlying_id']
                    records.append(record)
                if not entries: continue
        except Exception as exc:
            failed=True; receipt.error(f"{source['source_id']}: {type(exc).__name__}: {exc}")
    receipt.output_count=len(records); emit(records)
    return 1 if failed else 0

def main():
    if len(sys.argv)!=3 or sys.argv[1] not in ('feed','youtube','podcast'):
        print('Usage: collect.py feed|youtube|podcast RUN_DIR',file=sys.stderr); return 2
    kind=sys.argv[1]
    try:
        run=repo_path(sys.argv[2])
        if not (run/'run.json').is_file(): raise BadInput('RUN_DIR must contain run.json')
    except BadInput as exc: print(str(exc),file=sys.stderr); return 2
    stage={'feed':'feeds','youtube':'youtube','podcast':'podcasts'}[kind]
    rec=Receipt(run,'collectors/fetch_'+stage,tools=['python3','urllib RSS/Atom'] if kind!='youtube' else ['python3','yt-dlp'])
    try: code=run_collector(run,rec,kind)
    except (BadInput,ValueError,TypeError) as exc: rec.error(exc); code=2
    rec.save(code); return code
if __name__=='__main__': raise SystemExit(main())
