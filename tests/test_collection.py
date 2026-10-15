import importlib.util
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
collect=load('collect',BASE/'collectors'/'collect.py')
extract=load('extract',BASE/'processing'/'extract_content.py')

class CollectionTests(unittest.TestCase):
    def test_rss_and_atom_normalization(self):
        rss=b'''<rss><channel><item><title>Story</title><link>/story</link><pubDate>Sun, 11 Oct 2026 12:00:00 GMT</pubDate></item><item><title>Bad date</title><link>https://x.test/b</link><pubDate>n/a</pubDate></item></channel></rss>'''
        entries=collect.parse_feed(rss,'https://site.test/feed.xml')
        self.assertEqual(entries[0]['url'],'https://site.test/story')
        self.assertEqual(entries[0]['published_at'],'2026-10-11T12:00:00Z')
        self.assertIsNone(entries[1]['published_at'])
        atom=b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>tag:x,1</id><title>A</title><link href="/a"/><updated>2026-10-10T08:00:00-04:00</updated></entry></feed>'''
        a=collect.parse_feed(atom,'https://site.test/feed')
        self.assertEqual(a[0]['url'],'https://site.test/a')
        self.assertIsNone(a[0]['published_at'])
        self.assertIsNone(a[0]['source_date_field'])
        precedence=b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x</id><title>A</title><link href="/a"/><updated>2026-10-12T10:00:00Z</updated><published>2026-10-09T08:00:00-04:00</published></entry></feed>'''
        published=collect.parse_feed(precedence,'https://site.test/feed')[0]
        self.assertEqual(published['published_at'],'2026-10-09T12:00:00Z')
        self.assertEqual(published['source_date_field'],'published')
        self.assertEqual(published['publication_precision'],'timestamp')
        self.assertEqual(collect.date_value('20261012'),'2026-10-12T00:00:00Z')
        self.assertEqual(collect.date_details('20261012'),('2026-10-12T00:00:00Z','day'))
        self.assertEqual(collect.date_value('2026-10-09T08:00:00'),None)
        podcast=collect.parse_feed(b'<rss><channel><item><title>Image</title><link>/i</link><enclosure url="/cover.jpg" type="image/jpeg"/></item><item><title>Episode</title><link>/e</link><enclosure url="/ep.mp3" type="audio/mpeg"/></item></channel></rss>','https://pod.test/feed')
        self.assertIsNone(podcast[0]['media_url'])
        self.assertEqual(podcast[1]['media_url'],'https://pod.test/ep.mp3')

    def test_valid_empty_feed_is_success_and_discovery_has_retrieval_time(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td); (run/'config').mkdir()
            (run/'config/sources.json').write_text(json.dumps([{'source_id':'s','publisher_id':'p','kind':'feed','url':'https://site.test/feed'}]))
            empty=io.StringIO()
            with patch.object(collect,'fetch',return_value=(b'<rss><channel/></rss>','https://site.test/feed')), patch('sys.stdout',empty):
                receipt=__import__('sys').modules['common'].Receipt(run,'test')
                self.assertEqual(collect.run_collector(run,receipt,'feed'),0)
            self.assertEqual(empty.getvalue(),'')
            feed=b'<rss><channel><item><title>Story</title><link>/story</link><pubDate>Sun, 11 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>'
            out=io.StringIO()
            with patch.object(collect,'fetch',return_value=(feed,'https://site.test/feed')), patch('sys.stdout',out):
                receipt=__import__('sys').modules['common'].Receipt(run,'test')
                self.assertEqual(collect.run_collector(run,receipt,'feed'),0)
            self.assertIsNotNone(json.loads(out.getvalue())['retrieved_at'])

    def test_youtube_candidate_keeps_day_precision_and_source_field(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td); (run/'config').mkdir()
            (run/'config/sources.json').write_text(json.dumps([{'source_id':'yt','publisher_id':'p','kind':'youtube','url':'https://youtube.test/channel','max_items':1}]))
            result=__import__('types').SimpleNamespace(returncode=0,stdout=json.dumps({'entries':[{'id':'native-1','title':'Video','webpage_url':'https://youtube.test/watch?v=native-1','upload_date':'20261011'}]}),stderr='')
            out=io.StringIO()
            with patch.object(collect.subprocess,'run',return_value=result) as mocked, patch('sys.stdout',out):
                receipt=__import__('sys').modules['common'].Receipt(run,'test')
                self.assertEqual(collect.run_collector(run,receipt,'youtube'),0)
            self.assertNotIn('--flat-playlist',mocked.call_args.args[0])
            item=json.loads(out.getvalue())
            self.assertEqual(item['item_id'],'youtube:native-1')
            self.assertEqual(item['published_at'],'2026-10-11T00:00:00Z')
            self.assertEqual(item['publication_precision'],'day')
            self.assertEqual(item['source_date_field'],'upload_date')

    def test_live_sources_always_come_from_snapshot(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{'PS4_SOURCES_FILE':'/tmp/non-live-fixture.json'}):
            with self.assertRaises(__import__('sys').modules['common'].BadInput):
                collect.load_sources(Path(td),'feed')

    def test_standalone_wrappers_load_repo_environment_without_ps4_exports(self):
        wrapper=BASE/'processing'/'extract_content.sh'
        env={k:v for k,v in os.environ.items() if not k.startswith('PS4_')}
        env.update({'PATH':'/usr/bin:/bin','HOME':tempfile.gettempdir()})
        script=f'source \"{BASE}/lib/env.sh\"; test \"$PS4_ROOT\" = \"{BASE}\"; command -v yt-dlp'
        probe=subprocess.run(['bash','-c',script],env=env,capture_output=True,text=True)
        venv_ytdlp=BASE/'.venv'/'bin'/'yt-dlp'
        if venv_ytdlp.exists():
            self.assertEqual(Path(probe.stdout.strip()),venv_ytdlp)
        else:
            self.assertEqual(probe.returncode,0)
        invoked=subprocess.run(['bash',str(wrapper)],env=env,capture_output=True,text=True)
        self.assertEqual(invoked.returncode,2)
        self.assertIn('Usage: extract_content.py RUN_DIR',invoked.stderr)

    def test_transcript_segment_times(self):
        rows=extract.vtt_segments('WEBVTT\n\n00:00:01.200 --> 00:00:03.500\nHello world\n')
        self.assertEqual(rows[0]['start_seconds'],1.2)
        self.assertEqual(rows[0]['end_seconds'],3.5)
        self.assertEqual(rows[0]['text'],'Hello world')
        publisher=extract.timestamped_text_segments('00:00:01 Hello there\n00:00:03 Next thought')
        self.assertEqual([x['start_seconds'] for x in publisher],[1.0,3.0])
        transistor=extract.timestamped_text_segments('<cite>Name:</cite><time>00:01</time><p>First sentence.</p><cite>Guest:</cite><time>00:04</time><p>Second sentence.</p>')
        self.assertEqual(transistor[0]['end_seconds'],4.0)
        self.assertEqual(transistor[1]['end_seconds'],None)
        receipt=__import__('types').SimpleNamespace(extra={})
        rows=[{'segment_id':'s-1','start_seconds':1.0,'end_seconds':None,'text':'last'}]
        self.assertEqual(extract.finalize_segments([dict(rows[0])],7.0,receipt,'p:1')[0]['end_seconds'],7.0)
        self.assertEqual(extract.finalize_segments([dict(rows[0])],None,receipt,'p:1'),[])
        self.assertTrue(receipt.extra['limitations'])

    def test_dynamic_article_footer_is_trimmed(self):
        body='A substantive article body.\nMore recent articles\nNew link: 2026-10-12\nAnother article'
        self.assertEqual(extract.trim_article_footer(body),'A substantive article body.')
        self.assertEqual(extract.trim_article_footer(body.replace('2026-10-12','2026-10-13')),'A substantive article body.')

    def test_content_hash_paths_are_immutable_and_stable(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            with patch.object(extract,'relative',side_effect=lambda p: str(Path(p).name)):
                a,key=extract.store_bytes(folder,b'same','.txt')
            with patch.object(extract,'relative',side_effect=lambda p: str(Path(p).name)):
                b,key2=extract.store_bytes(folder,b'same','.txt')
            self.assertEqual((a,key),(b,key2))
            self.assertEqual((folder/a).read_bytes(),b'same')

    def test_partial_failure_keeps_successful_written_item(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td)/'run'; run.mkdir(); (run/'run.json').write_text(json.dumps({'as_of_date':'2026-10-12'}))
            records=[{'item_id':'feed:one','source_id':'s','publisher_id':'p','kind':'feed','title':'one','url':'https://x.test/one'},
                     {'item_id':'podcast:two','source_id':'s','publisher_id':'p','kind':'podcast','title':'two','url':'https://x.test/two','media_url':'https://x.test/a.mp3'}]
            with patch.object(extract,'ROOT',Path(td)), patch.object(extract,'relative',side_effect=lambda p: str(Path(p).resolve().relative_to(Path(td).resolve()))), patch.object(extract,'load_cache',return_value={}), patch.object(extract,'download',side_effect=[(b'<article>'+b'Useful article text. '*30+b'</article>','text/html','https://x.test/one'),(b'audio','audio/mpeg','https://x.test/a.mp3')]), patch.object(extract,'shutil_which',return_value=None), patch.dict(os.environ,{},clear=True), patch('sys.stdin',io.StringIO('\n'.join(json.dumps(x) for x in records)+'\n')), patch('sys.stdout',io.StringIO()):
                rec=__import__('sys').modules['common'].Receipt(run,'test')
                code=extract.extract(run,rec)
                output=__import__('sys').stdout.getvalue().strip().splitlines()
            self.assertEqual(code,1)
            self.assertEqual(len(output),1)
            self.assertEqual(json.loads(output[0])['item_id'],'feed:one')
            self.assertTrue(any('transcript' in e for e in rec.errors))

    def test_identity_uses_native_youtube_id(self):
        self.assertEqual('youtube:abc123','youtube:'+'abc123')

    def test_whisper_offsets_are_milliseconds(self):
        with tempfile.TemporaryDirectory() as td:
            cli=Path(td)/'whisper-cli'; cli.write_text('mock'); model=Path(td)/'model'; model.write_text('mock')
            def invoke(args, **kwargs):
                out=Path(args[args.index('-of')+1])
                Path(str(out)+'.json').write_text(json.dumps({'transcription':[{'offsets':{'from':1250,'to':2300},'text':' words ' }]}))
                return __import__('types').SimpleNamespace(returncode=0,stderr='')
            temp=tempfile.TemporaryDirectory()
            with patch.object(extract,'shutil_which',return_value=str(cli)), patch.object(extract,'ffmpeg_to_wav',return_value=(temp,None)), patch.object(extract.subprocess,'run',side_effect=invoke):
                rows=extract.whisper_segments(b'audio','.mp3',str(model))
            self.assertEqual(rows[0]['start_seconds'],1.25)
            self.assertEqual(rows[0]['end_seconds'],2.3)

    def test_same_metadata_written_source_is_refetched_and_content_versioned(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'data/assets').mkdir(parents=True)
            candidate={'item_id':'feed:stable','source_id':'s','publisher_id':'p','kind':'feed','title':'Title','url':'https://x.test/a','published_at':'2026-10-10T00:00:00Z','media_url':None}
            run=root/'run'; run.mkdir(); output=io.StringIO()
            def invoke(cache,raw,normalized):
                output=io.StringIO()
                with patch.object(extract,'ROOT',root), patch.object(extract,'relative',side_effect=lambda p:str(Path(p).resolve().relative_to(root.resolve()))), patch.object(extract,'load_cache',return_value=cache), patch.object(extract,'download',return_value=(raw,'text/html',candidate['url'])), patch.object(extract,'clean_html',return_value=normalized), patch('sys.stdin',io.StringIO(json.dumps(candidate)+'\n')), patch('sys.stdout',output):
                    rec=__import__('sys').modules['common'].Receipt(run,'test')
                    code=extract.extract(run,rec)
                self.assertEqual(code,0)
                return json.loads(output.getvalue()),rec
            first,_=invoke({},b'<html>source version 1</html>','A substantive article body '*20)
            second,receipt=invoke({first['item_id']:first},b'<html>source version 2, changed chrome</html>','A substantive article body '*20)
            self.assertEqual(first['version_id'],second['version_id'])
            self.assertNotEqual(first['media_path'],second['media_path'])
            self.assertEqual(receipt.extra['cache_hits'],0)
            third,_=invoke({second['item_id']:second},b'<html>source version 3</html>','A materially revised substantive article body '*20)
            self.assertNotEqual(second['version_id'],third['version_id'])

    def test_podcast_output_always_has_timestamped_segments(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); run=root/'run'; run.mkdir()
            (run/'run.json').write_text(json.dumps({'as_of_date':'2026-10-12'}))
            candidate={'item_id':'podcast:p1','source_id':'s','publisher_id':'p','kind':'podcast','title':'Episode','url':'https://pod.test/episode','published_at':'2026-10-12T00:00:00Z','media_url':'https://pod.test/audio.mp3','transcript_url':'https://pod.test/transcript'}
            responses=[(b'audio bytes','audio/mpeg',candidate['media_url']),(b'<cite>Host:</cite><time>00:01</time><p>First passage.</p><cite>Guest:</cite><time>00:04</time><p>Second passage.</p>','text/html',candidate['transcript_url'])]
            output=io.StringIO()
            with patch.object(extract,'ROOT',root), patch.object(extract,'relative',side_effect=lambda p:str(Path(p).resolve().relative_to(root.resolve()))), patch.object(extract,'load_cache',return_value={}), patch.object(extract,'download',side_effect=responses), patch.object(extract,'media_duration',return_value=8.0), patch('sys.stdin',io.StringIO(json.dumps(candidate)+'\n')), patch('sys.stdout',output):
                rec=__import__('sys').modules['common'].Receipt(run,'test')
                code=extract.extract(run,rec)
            self.assertEqual(code,0)
            item=json.loads(output.getvalue())
            self.assertIsNotNone(item['segments_path'])
            self.assertIsNotNone(item['transcript_path'])
            self.assertTrue((root/item['transcript_path']).exists())
            segments=json.loads((root/item['segments_path']).read_text())
            self.assertEqual(segments[-1]['end_seconds'],8.0)

    def test_youtube_local_asr_skips_subtitles_and_records_model_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); run=root/'run'; run.mkdir()
            (run/'run.json').write_text(json.dumps({'as_of_date':'2026-10-12'}))
            model=root/'ggml-small.bin'; model.write_bytes(b'mocked local model weights')
            candidate={'item_id':'youtube:video1','source_id':'yt','publisher_id':'pub','kind':'youtube','title':'Video','url':'https://youtube.test/watch?v=video1','published_at':'2026-10-11T00:00:00Z','publication_precision':'day','source_date_field':'upload_date','media_url':None,'native_id':'video1'}
            whisper_json={'transcription':[{'offsets':{'from':1500,'to':2750},'text':' Local transcription. '}]}
            calls={'yt':0,'whisper':0}
            def invoke(args,**kwargs):
                if args[0]=='/mock/yt-dlp':
                    calls['yt']+=1
                    self.assertIn('--no-playlist',args)
                    self.assertEqual(args[args.index('--retries')+1],'0')
                    self.assertEqual(args[args.index('--fragment-retries')+1],'0')
                    self.assertFalse(any('sub' in a.lower() for a in args))
                    self.assertFalse(any('cookie' in a.lower() or 'proxy' in a.lower() for a in args))
                    template=args[args.index('-o')+1]
                    Path(template.replace('.%(ext)s','.m4a')).write_bytes(b'public audio bytes')
                    return __import__('types').SimpleNamespace(returncode=0,stderr='')
                calls['whisper']+=1
                base=Path(args[args.index('-of')+1])
                Path(str(base)+'.json').write_text(json.dumps(whisper_json))
                return __import__('types').SimpleNamespace(returncode=0,stderr='')
            def wav(raw,ext,run_dir):
                temp=tempfile.TemporaryDirectory(); (Path(temp.name)/'audio.wav').write_bytes(b'wav')
                return temp,None
            def process(cache):
                output=io.StringIO()
                with patch.object(extract,'ROOT',root), patch.object(extract,'relative',side_effect=lambda p:str(Path(p).resolve().relative_to(root.resolve()))), patch.object(extract,'load_cache',return_value=cache), patch.object(extract,'shutil_which',side_effect=lambda name:'/mock/yt-dlp' if 'yt' in name else '/mock/whisper'), patch.object(extract,'ffmpeg_to_wav',side_effect=wav), patch.object(extract.subprocess,'run',side_effect=invoke), patch.object(extract,'media_duration',return_value=5.0), patch.dict(os.environ,{'PS4_YOUTUBE_TRANSCRIPT_MODE':'local','PS4_WHISPER_MODEL':str(model),'PS4_WHISPER_CLI':'whisper-cli','PS4_YTDLP':'yt-dlp'},clear=True), patch('sys.stdin',io.StringIO(json.dumps(candidate)+'\n')), patch('sys.stdout',output):
                    receipt=__import__('sys').modules['common'].Receipt(run,'test')
                    code=extract.extract(run,receipt)
                self.assertEqual(code,0)
                return json.loads(output.getvalue()),receipt
            first,receipt=process({})
            self.assertEqual(first['transcript_method'],'whisper-cli-local')
            self.assertEqual(first['transcript_verification'],'machine_generated_unverified')
            self.assertEqual(first['transcript_model'],'ggml-small.bin')
            self.assertEqual(first['transcript_model_sha256'],hashlib.sha256(model.read_bytes()).hexdigest())
            self.assertIn('upload_date',first['source_date_field'])
            self.assertEqual(receipt.extra['youtube_transcript_mode'],'local')
            self.assertEqual(receipt.extra['transcript_provenance'][0]['transcript_method'],'whisper-cli-local')
            self.assertTrue(first['transcript_path'].endswith('.whisper.json'))
            saved=json.loads((root/first['transcript_path']).read_text())
            self.assertEqual(saved,whisper_json)
            segments=json.loads((root/first['segments_path']).read_text())
            self.assertEqual(segments[0]['start_seconds'],1.5)
            self.assertEqual(segments[0]['end_seconds'],2.75)
            second,second_receipt=process({first['item_id']:first})
            self.assertEqual(calls['yt'],1)
            self.assertEqual(calls['whisper'],2)
            self.assertEqual(first['version_id'],second['version_id'])
            self.assertEqual(second_receipt.extra['cache_hits'],1)

    def test_stored_or_local_reuses_complete_cached_youtube_assets_without_work(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); run=root/'run'; (run/'config').mkdir(parents=True)
            (run/'config/processing.json').write_text(json.dumps({'youtube_transcript_mode':'stored_or_local','whisper_model':'models/missing-model.bin','whisper_cli':'/platform/whisper-cli'}))
            (run/'run.json').write_text(json.dumps({'as_of_date':'2026-10-12'}))
            candidate={'item_id':'youtube:retained','source_id':'yt','publisher_id':'pub','kind':'youtube','title':'Video','url':'https://youtube.test/watch?v=retained','published_at':'2026-10-11T00:00:00Z','publication_precision':'day','source_date_field':'upload_date','media_url':None,'native_id':'retained'}
            (root/'data/assets').mkdir(parents=True); (root/'data/media').mkdir(parents=True)
            (root/'data/assets/text.txt').write_text('Previously retained transcript.')
            segments=[{'segment_id':'s-0001','start_seconds':0.0,'end_seconds':3.0,'text':'Previously retained transcript.'}]
            (root/'data/assets/segments.json').write_text(json.dumps(segments))
            (root/'data/media/audio.m4a').write_bytes(b'audio')
            (root/'data/media/transcript.vtt').write_text('WEBVTT\\n')
            old={**candidate,'publication_precision':'timestamp','source_date_field':'release_date','retrieved_at':'2026-10-12T00:00:00Z','version_id':'old-version','text_path':'data/assets/text.txt','segments_path':'data/assets/segments.json','media_path':'data/media/audio.m4a','transcript_path':'data/media/transcript.vtt','content_hash':'old-hash','transcript_method':'youtube_captions','transcript_model':None,'transcript_model_sha256':None,'transcript_verification':'platform_caption_unverified'}
            output=io.StringIO()
            with patch.object(extract,'ROOT',root), patch.object(extract,'relative',side_effect=lambda p:str(Path(p).resolve().relative_to(root.resolve()))), patch.object(extract,'load_cache',return_value={old['item_id']:old}), patch.object(extract,'download',side_effect=AssertionError('must not download')), patch.object(extract.subprocess,'run',side_effect=AssertionError('must not invoke downloader or ASR')), patch.object(extract,'whisper_result',side_effect=AssertionError('must not transcribe')), patch.dict(os.environ,{},clear=True), patch('sys.stdin',io.StringIO(json.dumps(candidate)+'\n')), patch('sys.stdout',output):
                receipt=__import__('sys').modules['common'].Receipt(run,'test')
                code=extract.extract(run,receipt)
            self.assertEqual(code,0)
            item=json.loads(output.getvalue())
            self.assertEqual(item['transcript_method'],'youtube_captions')
            self.assertEqual(item['transcript_path'],old['transcript_path'])
            self.assertEqual(item['segments_path'],old['segments_path'])
            self.assertEqual(item['media_path'],old['media_path'])
            self.assertEqual(receipt.extra['youtube_transcript_mode'],'stored_or_local')
            self.assertEqual(receipt.extra['youtube_transcript_mode_source'],'run/config/processing.json')
            self.assertEqual(receipt.extra['cache_hits'],1)
            self.assertTrue(receipt.extra['limitations'])

    def test_default_youtube_caption_failure_uses_zero_retries_and_keeps_error(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); run=root/'run'; run.mkdir()
            candidate={'item_id':'youtube:429','source_id':'yt','publisher_id':'p','kind':'youtube','title':'Video','url':'https://youtube.test/watch?v=429','published_at':None,'media_url':None}
            output=io.StringIO(); failure=__import__('types').SimpleNamespace(returncode=1,stderr='HTTP Error 429: Too Many Requests')
            with patch.object(extract,'ROOT',root), patch.object(extract,'load_cache',return_value={}), patch.object(extract,'shutil_which',return_value='/mock/yt-dlp'), patch.object(extract.subprocess,'run',return_value=failure) as mocked, patch.dict(os.environ,{},clear=True), patch('sys.stdin',io.StringIO(json.dumps(candidate)+'\n')), patch('sys.stdout',output):
                receipt=__import__('sys').modules['common'].Receipt(run,'test')
                code=extract.extract(run,receipt)
            args=mocked.call_args.args[0]
            self.assertEqual(code,1)
            self.assertEqual(receipt.extra['youtube_transcript_mode'],'captions')
            self.assertIn('--write-auto-subs',args)
            self.assertEqual(args[args.index('--retries')+1],'0')
            self.assertEqual(args[args.index('--fragment-retries')+1],'0')
            self.assertTrue(any('HTTP Error 429' in error for error in receipt.errors))

if __name__=='__main__': unittest.main()
