#!/usr/bin/env python3
"""Fetch and retain source material as immutable, content-addressed assets."""
import datetime as dt
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from common import BadInput, Receipt, emit, read_jsonl, relative, repo_path  # noqa: E402

MAX_TEXT_BYTES=24*1024*1024
MAX_MEDIA_BYTES=220*1024*1024

def sha(data): return hashlib.sha256(data).hexdigest()
def file_sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()
def download(url, max_bytes=MAX_TEXT_BYTES, timeout=35):
    last=None
    for attempt in range(3):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'PS04ResearchBot/1.0'})
            with urllib.request.urlopen(req,timeout=timeout) as r:
                length=r.headers.get('Content-Length')
                if length and int(length)>max_bytes: raise RuntimeError(f'resource exceeds {max_bytes} byte download limit')
                chunks=[]; total=0
                while True:
                    block=r.read(min(1024*1024,max_bytes-total+1))
                    if not block: break
                    total+=len(block)
                    if total>max_bytes: raise RuntimeError(f'resource exceeds {max_bytes} byte download limit')
                    chunks.append(block)
                return b''.join(chunks),r.headers.get_content_type(),r.geturl()
        except Exception as exc:
            last=exc
            if attempt<2: time.sleep(.25*(attempt+1))
    raise last

def store_bytes(folder,data,suffix):
    folder.mkdir(parents=True,exist_ok=True); key=sha(data); path=folder/(key+suffix)
    if not path.exists(): path.write_bytes(data)
    return relative(path),key

def clean_html(data):
    source=data.decode('utf-8','replace')
    try:
        import trafilatura
        extracted=trafilatura.extract(source,include_comments=False,include_tables=True, favor_precision=False)
        if extracted and len(extracted.strip())>=160: return extracted.strip()
    except Exception: pass
    s=re.sub(r'(?is)<(script|style|nav|footer|header|noscript|svg)[^>]*>.*?</\1>',' ',source)
    s=re.sub(r'(?i)</(p|div|article|section|h[1-6]|li|br|tr)>','\n',s)
    s=re.sub(r'<[^>]+>',' ',s)
    s=html.unescape(s)
    return '\n'.join(x.strip() for x in s.splitlines() if x.strip())

def trim_article_footer(text):
    marker=re.search(r'(?im)^\s*More recent articles\s*$',text)
    return text[:marker.start()].rstrip() if marker else text

def timestamped_text_segments(text):
    """Read transcript rows whose publisher explicitly supplies clock marks."""
    publisher_rows=re.findall(r'<time\b[^>]*>\s*((?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)\s*</time>\s*<p\b[^>]*>(.*?)</p>',text,re.I|re.S)
    if publisher_rows:
        parsed=[]
        for stamp,body in publisher_rows:
            plain=clean_html(body.encode('utf-8','replace'))
            parts=stamp.replace(',','.').split(':')
            seconds=sum(float(v)*60**(len(parts)-i-1) for i,v in enumerate(parts))
            if plain: parsed.append((seconds,plain))
        return [{'segment_id':f's-{i+1:04d}','start_seconds':start,'end_seconds':parsed[i+1][0] if i+1<len(parsed) else None,'text':body} for i,(start,body) in enumerate(parsed)]
    flat=clean_html(text.encode('utf-8','replace')) if '<' in text else text
    pattern=re.compile(r'(?m)(?<!\d)(?P<t>(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)(?:\s+|\s*[-–:]\s*)(?P<body>.*?)(?=(?<!\d)(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?(?:\s+|\s*[-–:]\s*)|$)',re.S)
    found=[]
    def sec(value):
        parts=value.replace(',', '.').split(':')
        return sum(float(v)*60**(len(parts)-i-1) for i,v in enumerate(parts))
    for m in pattern.finditer(flat):
        body=' '.join(m.group('body').split())
        if body: found.append((sec(m.group('t')),body))
    return [{'segment_id':f's-{i+1:04d}','start_seconds':t,'end_seconds':found[i+1][0] if i+1<len(found) else None,'text':body} for i,(t,body) in enumerate(found)]

def vtt_segments(text):
    rows=[]
    for block in re.split(r'\n\s*\n',text.replace('\r','')):
        lines=block.strip().splitlines(); timing=next((x for x in lines if '-->' in x),None)
        if not timing: continue
        a,b=timing.split('-->',1); b=b.split()[0]
        def sec(v):
            vals=v.replace(',','.').split(':'); return sum(float(x)*60**(len(vals)-i-1) for i,x in enumerate(vals))
        try: start,end=sec(a.strip()),sec(b.strip())
        except ValueError: continue
        tx=' '.join(re.sub(r'<[^>]*>','',x).strip() for x in lines[lines.index(timing)+1:] if x.strip())
        if tx: rows.append({'segment_id':f's-{len(rows)+1:04d}','start_seconds':start,'end_seconds':end,'text':tx})
    return rows

def media_duration(path):
    ffprobe=os.environ.get('PS4_FFPROBE','ffprobe')
    try:
        p=subprocess.run([ffprobe,'-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)],capture_output=True,text=True,timeout=25)
        if p.returncode==0: return float(p.stdout.strip())
    except (OSError,ValueError,subprocess.TimeoutExpired): pass
    ffmpeg=os.environ.get('PS4_FFMPEG','ffmpeg')
    try:
        p=subprocess.run([ffmpeg,'-i',str(path)],capture_output=True,text=True,timeout=25)
        match=re.search(r'Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)',p.stderr)
        if match:
            h,m,s=match.groups()
            return int(h)*3600+int(m)*60+float(s)
    except (OSError,ValueError,subprocess.TimeoutExpired): pass
    return None

def finalize_segments(segments,duration,receipt,item_id):
    if not segments: return []
    segments=sorted(segments,key=lambda s:s['start_seconds'])
    for i,row in enumerate(segments):
        if row.get('end_seconds') is None and i+1<len(segments): row['end_seconds']=segments[i+1]['start_seconds']
    if segments[-1].get('end_seconds') is None:
        if duration is not None and duration>segments[-1]['start_seconds']:
            segments[-1]['end_seconds']=duration
        else:
            segments.pop()
            receipt.extra.setdefault('limitations',[]).append(f'{item_id}: dropped final timestamped transcript tail because neither a segment end nor media duration was available')
    return [s for s in segments if s.get('end_seconds') is not None and s['end_seconds']>s['start_seconds'] and s.get('text','').strip()]

def cache_get(item_id):
    # Kept as a small compatibility helper for tests and focused callers.
    p=subprocess.run(['bash',str(ROOT/'data'/'store.sh'),'get',item_id],capture_output=True,text=True,timeout=20)
    if p.returncode: return None
    try: return json.loads(p.stdout)
    except ValueError: return None

def load_cache():
    p=subprocess.run(['bash',str(ROOT/'data'/'store.sh'),'list'],capture_output=True,text=True,timeout=45)
    if p.returncode: raise RuntimeError('evidence store list failed: '+p.stderr[-500:])
    records=[]
    for n,line in enumerate(p.stdout.splitlines(),1):
        try: records.append(json.loads(line))
        except ValueError as exc: raise RuntimeError(f'evidence store list returned malformed JSONL at line {n}') from exc
    return {r['item_id']:r for r in records if isinstance(r,dict) and isinstance(r.get('item_id'),str)}

def asset_exists(path):
    if not path: return False
    try: return (ROOT/path).is_file()
    except (OSError,TypeError): return False

def cache_match(candidate,old):
    if not old: return False
    ignored={'retrieved_at','version_id','text_path','segments_path','media_path','transcript_path','content_hash',
             'transcript_method','transcript_model','transcript_model_sha256','transcript_verification',
             'publication_precision','source_date_field'}
    candidate_meta={k:v for k,v in candidate.items() if k not in ignored}
    old_meta={k:v for k,v in old.items() if k not in ignored}
    if candidate_meta!=old_meta: return False
    if not asset_exists(old.get('text_path')): return False
    if candidate['kind'] in ('podcast','youtube') and not asset_exists(old.get('segments_path')): return False
    if candidate['kind'] in ('podcast','youtube') and not asset_exists(old.get('media_path')): return False
    if old.get('transcript_path') and not asset_exists(old.get('transcript_path')): return False
    return True

def processing_settings(run):
    snapshot=run/'config'/'processing.json'
    config={}
    if snapshot.is_file():
        try: config=json.loads(snapshot.read_text())
        except (OSError,ValueError) as exc: raise BadInput(f'Cannot read processing settings snapshot: {exc}') from exc
        if not isinstance(config,dict): raise BadInput('config/processing.json must contain an object')
    env_mode=os.environ.get('PS4_YOUTUBE_TRANSCRIPT_MODE')
    mode=(env_mode or config.get('youtube_transcript_mode') or 'captions').strip().lower()
    if mode not in ('captions','local','stored_or_local'): raise BadInput('YouTube transcript mode must be captions, local, or stored_or_local')
    env_model=os.environ.get('PS4_WHISPER_MODEL')
    model=env_model or config.get('whisper_model')
    if model:
        model_path=Path(model)
        if not model_path.is_absolute(): model_path=ROOT/model_path
        model=str(model_path.resolve())
    else: model=None
    env_cli=os.environ.get('PS4_WHISPER_CLI')
    cli=env_cli or config.get('whisper_cli') or 'whisper-cli'
    return (mode,model,cli,
            'environment' if env_mode else 'run/config/processing.json' if snapshot.is_file() else 'default',
            'environment' if env_model else 'run/config/processing.json' if config.get('whisper_model') else 'default',
            'environment' if env_cli else 'run/config/processing.json' if config.get('whisper_cli') else 'default')

def old_segments(old):
    if not old or not asset_exists(old.get('segments_path')): return None
    try:
        value=json.loads((ROOT/old['segments_path']).read_text())
        return value if isinstance(value,list) and value else None
    except (OSError,ValueError,TypeError): return None

def retain_transcript(raw,mime,url):
    suffix=Path(url.split('?',1)[0]).suffix.lower()
    if not suffix or len(suffix)>8: suffix={ 'text/vtt':'.vtt','text/html':'.html','application/json':'.json' }.get(mime,'.transcript')
    return store_bytes(ROOT/'data'/'media',raw,suffix)[0]

def validate_candidates(candidates):
    for n,c in enumerate(candidates,1):
        if not isinstance(c,dict): raise BadInput(f'candidate line {n} must be an object')
        for k in ('item_id','source_id','publisher_id','kind','title','url'):
            if not isinstance(c.get(k),str) or not c[k]: raise BadInput(f'candidate line {n}: {k} must be nonempty string')
        if c['kind'] not in ('feed','youtube','podcast'): raise BadInput(f'candidate line {n}: unsupported kind')
        if not c['url'].startswith(('https://','http://')): raise BadInput(f'candidate line {n}: url must use http or https')
        if c['kind']=='podcast' and not isinstance(c.get('media_url'),str): raise BadInput(f'candidate line {n}: podcast media_url must be supplied')
        for k in ('published_at','media_url','transcript_url','retrieved_at','underlying_id'):
            if c.get(k) is not None and not isinstance(c[k],str): raise BadInput(f'candidate line {n}: {k} must be string or null')

def ffmpeg_to_wav(raw,ext,run_dir):
    ffmpeg=os.environ.get('PS4_FFMPEG','ffmpeg')
    td=tempfile.TemporaryDirectory(); inp=Path(td.name)/('input'+(ext if ext.startswith('.') else '.bin')); out=Path(td.name)/'audio.wav'; inp.write_bytes(raw)
    try:
        p=subprocess.run([ffmpeg,'-nostdin','-y','-i',str(inp),'-ar','16000','-ac','1','-c:a','pcm_s16le',str(out)],capture_output=True,text=True,timeout=600)
        if p.returncode or not out.is_file(): td.cleanup(); raise RuntimeError('ffmpeg 16 kHz mono conversion failed: '+p.stderr[-500:])
        return td,out
    except FileNotFoundError:
        td.cleanup(); raise RuntimeError('ffmpeg is required for whisper-cli transcription; set PS4_FFMPEG')

def whisper_result(raw,ext,model,cli=None):
    cli=cli or os.environ.get('PS4_WHISPER_CLI','whisper-cli')
    if not model: raise RuntimeError('audio retained, but publisher timestamped transcript unavailable and PS4_WHISPER_MODEL is unset')
    if not shutil_which(cli): raise RuntimeError('audio retained, but whisper-cli is unavailable (set PS4_WHISPER_CLI)')
    td,wavdir=ffmpeg_to_wav(raw,ext,None)
    try:
        wav=Path(td.name)/'audio.wav'; base=Path(td.name)/'result'
        p=subprocess.run([cli,'-m',model,'-f',str(wav),'-oj','-of',str(base)],capture_output=True,text=True,timeout=1800)
        jf=Path(str(base)+'.json')
        if p.returncode or not jf.exists(): raise RuntimeError('whisper-cli failed: '+p.stderr[-400:])
        raw_json=jf.read_bytes(); j=json.loads(raw_json.decode('utf-8')); rows=[]
        for i,x in enumerate(j.get('transcription',[])):
            stamps=x.get('offsets') or x.get('timestamps',{}); text=x.get('text','').strip()
            try: start=float(stamps['from'])/1000; end=float(stamps['to'])/1000
            except (TypeError,ValueError,KeyError): continue
            if text and end>start: rows.append({'segment_id':f's-{len(rows)+1:04d}','start_seconds':start,'end_seconds':end,'text':text})
        return rows,raw_json
    finally: td.cleanup()

def whisper_segments(raw,ext,model):
    return whisper_result(raw,ext,model)[0]

def transcript_provenance(method,model=None,model_hash=None):
    verification='machine_generated_unverified' if method=='whisper-cli-local' else 'platform_caption_unverified' if method=='youtube_captions' else 'publisher_provided'
    return {'transcript_method':method,'transcript_model':Path(model).name if model else None,
            'transcript_model_sha256':model_hash,'transcript_verification':verification}

def extract(run,receipt):
    candidates=read_jsonl(sys.stdin); validate_candidates(candidates); receipt.input_count=len(candidates)
    output=[]; receipt.extra['cache_hits']=0
    youtube_mode,whisper_model,whisper_cli,mode_source,model_source,cli_source=processing_settings(run)
    receipt.extra['youtube_transcript_mode']=youtube_mode
    receipt.extra['youtube_transcript_mode_source']=mode_source
    receipt.extra['whisper_model']=Path(whisper_model).name if whisper_model else None
    receipt.extra['whisper_model_source']=model_source
    receipt.extra['whisper_cli']=whisper_cli
    receipt.extra['whisper_cli_source']=cli_source
    receipt.extra['transcript_provenance']=[]
    receipt.extra['cache_items']=[]
    receipt.extra['limitations']=[]
    receipt.extra['cache_policy']='Written pages and publisher transcripts are refetched and normalized each run; YouTube captions are re-requested. Podcast and YouTube media may be reused for unchanged media URL and publication metadata, so mutable media bytes at an unchanged URL are not revalidated.'
    media_dir=ROOT/'data'/'media'; asset_dir=ROOT/'data'/'assets'
    try: cache=load_cache()
    except Exception as exc:
        receipt.error(f'evidence cache lookup failed; proceeding without reuse: {type(exc).__name__}: {exc}')
        cache={}
    for c in candidates:
        try:
            old=cache.get(c['item_id'])
            same_source=cache_match(c,old)
            content=None; media_path=None; seg_path=None; transcript_path=None; segments=[]; raw=None; ext='.bin'; duration=None
            provenance={'transcript_method':None,'transcript_model':None,'transcript_model_sha256':None,'transcript_verification':None}
            if c['kind']=='feed':
                raw,mime,final=download(c['url']); content=trim_article_footer(clean_html(raw))
                if len(content.strip())<250: raise RuntimeError('article extraction produced under 250 characters; refusing to treat metadata as full text')
                media_path,_=store_bytes(media_dir,raw,'.html')
            elif c['kind'] in ('podcast','youtube'):
                if c.get('published_at'):
                    try:
                        pub=dt.datetime.fromisoformat(c['published_at'].replace('Z','+00:00')).date()
                        asof=dt.date.fromisoformat(json.loads((run/'run.json').read_text())['as_of_date'])
                        if pub<asof-dt.timedelta(days=29): raise RuntimeError('skipped media outside 30-day window; candidate metadata retained')
                    except RuntimeError: raise
                    except Exception: pass
                if c['kind']=='podcast':
                    if not c.get('media_url'): raise RuntimeError('podcast candidate has no audio enclosure URL')
                    if same_source:
                        media_path=old.get('media_path')
                        raw=(ROOT/media_path).read_bytes()
                        receipt.extra['cache_hits']+=1
                    else:
                        raw,_,_=download(c['media_url'],MAX_MEDIA_BYTES,timeout=75); ext=Path(c['media_url'].split('?',1)[0]).suffix or '.bin'
                        media_path,_=store_bytes(media_dir,raw,ext)
                    ext=Path(c['media_url'].split('?',1)[0]).suffix or '.bin'
                    duration=media_duration(ROOT/media_path)
                    tr=c.get('transcript_url')
                    if tr:
                        tdata,tmime,tfinal=download(tr); transcript_path=retain_transcript(tdata,tmime,tfinal); txt=tdata.decode('utf-8','replace')
                        if tr.lower().endswith('.vtt') or 'WEBVTT' in txt[:300]: segments=vtt_segments(txt)
                        else:
                            segments=timestamped_text_segments(txt)
                            if not segments: content=clean_html(tdata) if '<' in txt[:1000] else txt
                    if not segments and not tr and same_source:
                        segments=old_segments(old)
                        if segments:
                            provenance={k:old.get(k) for k in provenance}
                    if segments and tr: provenance=transcript_provenance('publisher_timestamped')
                    if not segments:
                        model=whisper_model
                        segments,whisper_json=whisper_result(raw,ext,model,whisper_cli)
                        model_hash=file_sha(model)
                        provenance=transcript_provenance('whisper-cli-local',model,model_hash)
                        transcript_path,_=store_bytes(media_dir,whisper_json,'.whisper.json')
                    segments=finalize_segments(segments,duration,receipt,c['item_id'])
                    if not segments: raise RuntimeError('no usable timestamped transcript segments after preserving known times; publisher transcript was un-timestamped or final tail could not be timed')
                    content='\n'.join(x['text'] for x in segments)
                elif youtube_mode=='stored_or_local' and same_source:
                    segments=old_segments(old)
                    if not segments: raise RuntimeError('matching cached YouTube item lacks retained transcript segments')
                    content=(ROOT/old['text_path']).read_text(encoding='utf-8')
                    media_path=old['media_path']; seg_path=old['segments_path']; transcript_path=old.get('transcript_path')
                    provenance={k:old.get(k) for k in provenance}
                    if not provenance['transcript_method']:
                        provenance=transcript_provenance('retained_existing_transcript')
                        provenance['transcript_verification']='machine_or_publisher_unverified'
                    receipt.extra['cache_hits']+=1
                    receipt.extra['cache_items'].append({'item_id':c['item_id'],'method':provenance['transcript_method'],'cache_hit':True})
                    receipt.extra['limitations'].append(f"{c['item_id']}: reused retained media/transcript using source metadata; changes at an unchanged source URL cannot be detected")
                else:
                    if youtube_mode in ('local','stored_or_local'):
                        model=whisper_model
                        if not model or not Path(model).is_file(): raise RuntimeError('local YouTube transcription requires whisper_model in config/processing.json or PS4_WHISPER_MODEL to name an existing model file')
                        if not shutil_which(whisper_cli): raise RuntimeError(f'local YouTube transcription requires whisper-cli at {whisper_cli!r}')
                        model_hash=file_sha(model)
                        if same_source:
                            media_path=old.get('media_path'); raw=(ROOT/media_path).read_bytes(); ext=Path(media_path).suffix or '.bin'; receipt.extra['cache_hits']+=1
                        else:
                            binary=shutil_which(os.environ.get('PS4_YTDLP','yt-dlp'))
                            if not binary: raise RuntimeError('yt-dlp executable is required to retrieve YouTube audio')
                            with tempfile.TemporaryDirectory() as td:
                                template=str(Path(td)/'item.%(ext)s')
                                args=[binary,'--no-warnings','--no-playlist','--retries','0','--fragment-retries','0','--max-filesize','220M','-f','bestaudio/best','-o',template,c['url']]
                                p=subprocess.run(args,capture_output=True,text=True,timeout=1800)
                                if p.returncode: raise RuntimeError('yt-dlp audio retrieval failed: '+p.stderr[-500:])
                                audio=[x for x in Path(td).glob('item.*') if x.suffix.lower() not in ('.vtt','.json3')]
                                if not audio: raise RuntimeError('yt-dlp produced no YouTube audio file')
                                raw=audio[0].read_bytes()
                                if len(raw)>MAX_MEDIA_BYTES: raise RuntimeError('YouTube media exceeds configured 220 MiB limit')
                                ext=audio[0].suffix or '.bin'; media_path,_=store_bytes(media_dir,raw,ext)
                        duration=media_duration(ROOT/media_path)
                        segments,whisper_json=whisper_result(raw,ext,model,whisper_cli)
                        transcript_path,_=store_bytes(media_dir,whisper_json,'.whisper.json')
                        provenance=transcript_provenance('whisper-cli-local',model,model_hash)
                    else:
                        binary=shutil_which(os.environ.get('PS4_YTDLP','yt-dlp'))
                        if not binary: raise RuntimeError('yt-dlp executable is required to retrieve YouTube media/captions')
                        with tempfile.TemporaryDirectory() as td:
                            template=str(Path(td)/'item.%(ext)s')
                            args=[binary,'--no-warnings','--no-playlist','--retries','0','--fragment-retries','0','--write-auto-subs','--write-subs','--sub-langs','en.*,en','--sub-format','vtt','--max-filesize','220M','-o',template]
                            if same_source: args.append('--skip-download')
                            else: args += ['-f','bestaudio/best']
                            args.append(c['url'])
                            p=subprocess.run(args,capture_output=True,text=True,timeout=1800)
                            if p.returncode: raise RuntimeError('yt-dlp caption/media retrieval failed: '+p.stderr[-500:])
                            files=list(Path(td).glob('item.*')); audio=[x for x in files if x.suffix.lower() not in ('.vtt','.json3')]
                            if audio:
                                raw=audio[0].read_bytes()
                                if len(raw)>MAX_MEDIA_BYTES: raise RuntimeError('YouTube media exceeds configured 220 MiB limit')
                                ext=audio[0].suffix or '.bin'; media_path,_=store_bytes(media_dir,raw,ext)
                            elif same_source:
                                media_path=old.get('media_path'); raw=(ROOT/media_path).read_bytes()
                            else: raise RuntimeError('yt-dlp produced no media file')
                            duration=media_duration(ROOT/media_path)
                            subs=[x for x in files if x.suffix.lower()=='.vtt']
                            if subs:
                                transcript_raw=subs[0].read_bytes(); transcript_path,_=store_bytes(media_dir,transcript_raw,'.vtt')
                                segments=vtt_segments(transcript_raw.decode('utf-8','replace'))
                        if not segments and same_source:
                            segments=old_segments(old)
                            if segments: provenance={k:old.get(k) for k in provenance}
                        if segments and provenance['transcript_method'] is None:
                            provenance=transcript_provenance('youtube_captions')
                    segments=finalize_segments(segments,duration,receipt,c['item_id'])
                    if not segments: raise RuntimeError('YouTube media retained, but timestamped captions unavailable or unusable')
                    content='\n'.join(x['text'] for x in segments)
                if not seg_path:
                    seg_path,_=store_bytes(asset_dir,json.dumps(segments,ensure_ascii=False,indent=2).encode(),'.segments.json')
            else: raise BadInput(f"unsupported candidate kind {c['kind']!r}")
            if not content or not content.strip(): raise RuntimeError('no substantive text extracted')
            if c['kind'] in ('podcast','youtube'):
                for key,value in provenance.items(): c[key]=value
                receipt.extra['transcript_provenance'].append({'item_id':c['item_id'],**provenance})
            text_bytes=content.strip().encode('utf-8'); text_path,content_hash=store_bytes(asset_dir,text_bytes,'.txt')
            metadata={k:v for k,v in c.items() if k not in ('retrieved_at','publication_precision','source_date_field')}
            substantive={'metadata':metadata,'content_hash':content_hash,'segments':segments if segments else None}
            if c['kind'] in ('podcast','youtube'):
                substantive['transcript_provenance']=provenance
            version=sha(json.dumps(substantive,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())
            item={**c,'retrieved_at':dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'),'version_id':version,'text_path':text_path,'segments_path':seg_path,'media_path':media_path,'transcript_path':transcript_path,'content_hash':content_hash}
            output.append(item)
        except BadInput: raise
        except Exception as exc: receipt.error(f"{c['item_id']}: {type(exc).__name__}: {exc}")
    receipt.output_count=len(output); emit(output); return 1 if receipt.errors else 0

def shutil_which(name):
    import shutil
    return shutil.which(name)

def main():
    if len(sys.argv)!=2:
        print('Usage: extract_content.py RUN_DIR',file=sys.stderr); return 2
    try:
        run=repo_path(sys.argv[1])
        if not (run/'run.json').is_file(): raise BadInput('RUN_DIR must contain run.json')
    except BadInput as exc: print(str(exc),file=sys.stderr); return 2
    rec=Receipt(run,'processing/extract_content',tools=['python3','trafilatura (optional)','yt-dlp','ffmpeg','ffprobe','whisper-cli (optional)'])
    try: code=extract(run,rec)
    except (BadInput,ValueError,TypeError) as exc:
        rec.error(exc); code=2
    rec.save(code); return code
if __name__=='__main__': raise SystemExit(main())
