"""Isolated PS04 replay integration checks; records come from fictional examples."""
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[1]

class EditorialWorkflowReplay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ps4-editorial-replay-')
        self.root = Path(self.tmp.name) / 'ps4'
        shutil.copytree(SOURCE, self.root, ignore=shutil.ignore_patterns('.git', '__pycache__', 'store.sqlite3', 'runs', 'evidence', 'media', 'assets', 'docs'))
        self.run = self.root / 'replays' / 'replay-test'
        self.run.mkdir(parents=True)
        shutil.copytree(self.root / 'config', self.run / 'config')
        initial_ai=json.loads((self.run/'config/ai.json').read_text())
        initial_ai['enabled']=False
        (self.run/'config/ai.json').write_text(json.dumps(initial_ai))
        shutil.copytree(self.root / 'prompts', self.run / 'prompts')
        shutil.copyfile(self.root / 'examples/run.json', self.run / 'run.json')
        self.env = dict(os.environ, PS4_RUN_DIR='replays/replay-test', PS4_TEST_MODEL_MODE='valid', PYTHONDONTWRITEBYTECODE='1')
        self.items = [json.loads(x) for x in (self.root/'examples/items.jsonl').read_text().splitlines()]
        self.assertEqual(self.call('data/store.sh','init').returncode,0)
        up=self.call('data/store.sh','upsert','replays/replay-test',input=(self.root/'examples/items.jsonl').read_text())
        self.assertEqual(up.returncode,0,up.stderr)
        self.write_jsonl(self.run/'eligible.jsonl',self.items)
        self.stub=self.root/'tests'/'fixture_model_stub.py'
        self.stub.write_text('''import json, os, sys
p=json.load(sys.stdin); mode=os.environ.get("PS4_TEST_MODEL_MODE", "valid"); task=p.get("task")
if mode == "invalid_json": print("not json")
elif task == "select_items":
 rows=[{"item_id":x["item_id"],"version_id":x["version_id"],"decision":"accept","reason":"Fictional replay fixture decision.","piece_ids":["01","02","03"]} for x in p["evidence"]["items"]]
 if mode == "duplicate_decision" and rows: rows[-1]=dict(rows[0])
 if mode == "missing_decision" and rows: rows.pop()
 print(json.dumps({"decisions":rows}))
elif task == "create_briefs":
 rows=json.loads(os.environ["PS4_TEST_BRIEFS"])["briefs"]
 print(json.dumps({"brief":next(x for x in rows if x["piece_id"]==p["evidence"]["piece_id"]),"error":None}))
elif task.startswith("write_"):
 e=p["evidence"]; b=e["brief"]; ids=" ".join(c["claim_id"] for c in b["claims"]); date=e["as_of_date"]; urls=" ".join(x["url"] for x in e["items"])
 if mode == "missing_marker": ids=""
 if mode == "missing_citation": urls=""
 print(json.dumps({"markdown":("# Fictional replay draft\\n\\n"+date+"\\n\\n"+ids+"\\n\\n"+urls+"\\n")*8}))
else: print("{}")
''')
        self.env['PS4_MODEL_COMMAND']=json.dumps(['python3',str(self.stub)])

    def tearDown(self): self.tmp.cleanup()
    def call(self,script,*args,input=None,env=None):
        return subprocess.run(['bash',str(self.root/script),*args],cwd=self.root,env=env or self.env,
                              input=input,text=True,capture_output=True,timeout=40)
    @staticmethod
    def write_jsonl(path,rows):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
    def enable_stub(self):
        cfg=json.loads((self.run/'config/ai.json').read_text()); cfg['enabled']=True
        cfg['model_label']='local deterministic fixture stub'
        (self.run/'config/ai.json').write_text(json.dumps(cfg))
    def decision_rows(self):
        return [{'item_id':x['item_id'],'version_id':x['version_id'],'decision':'accept','reason':'fictional fixture','piece_ids':['01','02','03']} for x in self.items]
    def briefs(self,quote_override=None):
        refs=[]
        for item in self.items:
            if item['kind']=='feed':
                quote=quote_override if quote_override is not None else (self.root/item['text_path']).read_text().strip().splitlines()[0]
                loc={'type':'text','quote':quote}
            else:
                segments=json.loads((self.root/item['segments_path']).read_text()); loc={'type':'segment','segment_id':segments[0]['segment_id']}
            refs.append({'item_id':item['item_id'],'version_id':item['version_id'],'locator':loc})
        return [{'piece_id':pid,'title':'Fictional replay brief '+pid,'question':'What do the fictional records show?',
                 'argument':'Distinct fictional argument '+pid,'synthesis':'Fictional evidence synthesis across publishers.',
                 'limitations':'Invented example records make no real-world claim.',
                 'claims':[{'claim_id':pid+'-c1','statement':'The fictional records describe a measured process.',
                            'type':'inference','evidence':refs}]} for pid in ('01','02','03')]

    def test_disabled_inference_no_call_and_no_output(self):
        marker=self.root/'tests/model-was-called'
        self.stub.write_text(f'import pathlib,sys\npathlib.Path({str(marker)!r}).write_text("called")\nprint("{{}}")\n')
        env=dict(self.env,PS4_MODEL_COMMAND=json.dumps(['python3',str(self.stub)]))
        p=self.call('editorial/select_items.sh','replays/replay-test',input=(self.run/'eligible.jsonl').read_text(),env=env)
        self.assertNotEqual(p.returncode,0); self.assertEqual(p.stdout,''); self.assertFalse(marker.exists())
        self.assertIn('disabled',p.stderr)

    def test_invalid_json_and_duplicate_or_missing_decision_coverage_fail(self):
        self.enable_stub()
        for mode,fragment in [('invalid_json','valid JSON'),('duplicate_decision','exactly one decision'),('missing_decision','exactly one decision')]:
            env=dict(self.env,PS4_TEST_MODEL_MODE=mode)
            p=self.call('editorial/select_items.sh','replays/replay-test',input=(self.run/'eligible.jsonl').read_text(),env=env)
            self.assertNotEqual(p.returncode,0,mode); self.assertEqual(p.stdout,'',mode); self.assertIn(fragment,p.stderr)

    def test_selection_uses_captured_run_date_and_inclusive_utc_window(self):
        """The run snapshot, not the older feedback/config date, controls freshness context."""
        self.enable_stub()
        metadata=json.loads((self.run/'run.json').read_text())
        metadata['as_of_date']='2026-10-13'
        (self.run/'run.json').write_text(json.dumps(metadata))
        project=json.loads((self.run/'config/project.json').read_text())
        project['student_feedback_date']='2026-10-12'
        project['as_of_date']='2026-10-12'
        (self.run/'config/project.json').write_text(json.dumps(project))
        p=self.call('editorial/select_items.sh','replays/replay-test',input=(self.run/'eligible.jsonl').read_text())
        self.assertEqual(p.returncode,0,p.stderr)
        requests=list((self.run/'model_calls').glob('select_items-*.request.json'))
        self.assertTrue(requests,'selection should persist its provider-neutral model request')
        request=json.loads(requests[0].read_text())
        evidence=request['evidence']
        self.assertEqual(evidence['as_of_date'],'2026-10-13')
        self.assertEqual(evidence['freshness_window'],{
            'start_date':'2026-09-14','end_date':'2026-10-13','timezone':'UTC','inclusive':True})
        self.assertNotEqual(evidence['as_of_date'],project['student_feedback_date'])
        self.assertIn('2026-09-14 through 2026-10-13',request['instructions'])
        self.assertIn('do not infer dates from student feedback',request['instructions'])

    def test_selection_carries_forward_only_confirmed_exact_version_and_preserves_ai_result(self):
        self.enable_stub()
        item=dict(self.items[0]); changed=dict(item,version_id='changed-version-fixture')
        self.write_jsonl(self.run/'eligible.jsonl',[item,changed])
        revision=self.root/'revisions'/'test-confirmed-feedback'
        revision.mkdir(parents=True)
        source_id='fixture-authentic-feedback-message'
        feedback={'source_message_id':source_id,'user_message_at_utc':'2026-10-12T12:00:00Z',
                  'scope':{'six_sample_decisions_confirmed':True,'source_audio_verified_by_student':False,
                           'full_drafts_approved':False,'publication_authorized':False}}
        (revision/'student_feedback.json').write_text(json.dumps(feedback))
        sample={'item_id':item['item_id'],'version_id':item['version_id'],'student_decision':'reject',
                'source_message_id':source_id,'reviewed_at':'2026-10-12T12:00:00Z'}
        (revision/'student_review_sample.jsonl').write_text(json.dumps(sample)+'\n')
        prior={'item_id':item['item_id'],'version_id':item['version_id'],'decision':'accept',
               'reason':'Historical editorial rationale for the exact reviewed version.','piece_ids':['01','03']}
        (revision/'decisions.jsonl').write_text(json.dumps(prior)+'\n')
        project=json.loads((self.run/'config/project.json').read_text())
        project['student_feedback_record']='revisions/test-confirmed-feedback/student_feedback.json'
        (self.run/'config/project.json').write_text(json.dumps(project))
        p=self.call('editorial/select_items.sh','replays/replay-test',input=(self.run/'eligible.jsonl').read_text())
        self.assertEqual(p.returncode,0,p.stderr)
        rows=[json.loads(line) for line in p.stdout.splitlines()]
        by_version={row['version_id']:row for row in rows}
        carried=by_version[item['version_id']]
        self.assertEqual(carried['decision'],'reject')
        self.assertEqual(carried['reason'],prior['reason'])
        self.assertEqual(carried['piece_ids'],[])
        provenance=carried['selection_provenance']
        self.assertEqual(provenance['selected_by'],'exact_version_student_confirmed_sample')
        self.assertEqual(provenance['new_model_decision']['decision'],'accept')
        self.assertTrue(provenance['model_disagreed_with_student'])
        self.assertFalse(provenance['student_audio_verified'])
        self.assertFalse(provenance['full_draft_approval'])
        raw=[json.loads(line) for line in (self.run/'selection_ai_decisions.jsonl').read_text().splitlines()]
        self.assertEqual(next(x for x in raw if x['version_id']==item['version_id'])['decision'],'accept')
        self.assertEqual(by_version['changed-version-fixture']['decision'],'accept')
        self.assertNotIn('selection_provenance',by_version['changed-version-fixture'])
        snapshot=self.run/'student_feedback_carry_forward'
        manifest=json.loads((snapshot/'manifest.json').read_text())
        self.assertEqual(manifest['source_message_id'],source_id)
        self.assertFalse(manifest['student_audio_verified'])
        self.assertFalse(manifest['full_draft_approval'])
        self.assertFalse((self.run/'approval.json').exists())
        for name,digest in manifest['snapshots'].items():
            import hashlib
            self.assertEqual(hashlib.sha256((snapshot/name).read_bytes()).hexdigest(),digest)

    def test_fabricated_quote_rejected_and_too_few_independent_publishers_blocks_model(self):
        self.enable_stub()
        self.env['PS4_TEST_BRIEFS']=json.dumps({'briefs':self.briefs('A fabricated passage absent from this source.')})
        self.write_jsonl(self.run/'decisions.jsonl',self.decision_rows())
        p=self.call('editorial/create_briefs.sh','replays/replay-test',input=(self.run/'decisions.jsonl').read_text())
        self.assertNotEqual(p.returncode,0); self.assertEqual(p.stdout,''); self.assertIn('not exact',p.stderr)
        marker=self.root/'tests/brief-model-called'
        self.stub.write_text(f'import pathlib,sys\npathlib.Path({str(marker)!r}).write_text("called")\nprint("{{}}")\n')
        self.env['PS4_MODEL_COMMAND']=json.dumps(['python3',str(self.stub)])
        decisions=self.decision_rows()
        for d in decisions[2:]: d.update(decision='reject',piece_ids=[])
        self.write_jsonl(self.run/'decisions.jsonl',decisions)
        p=self.call('editorial/create_briefs.sh','replays/replay-test',input=(self.run/'decisions.jsonl').read_text())
        self.assertNotEqual(p.returncode,0); self.assertIn('three independent publishers',p.stderr); self.assertFalse(marker.exists())

    def test_generated_content_requires_markers_and_source_citations(self):
        self.enable_stub(); briefs=self.briefs(); self.write_jsonl(self.run/'briefs.jsonl',briefs)
        for mode,fragment in [('missing_marker','claim marker'),('missing_citation','source links')]:
            self.env['PS4_TEST_MODEL_MODE']=mode
            p=self.call('content/write_articles.sh','replays/replay-test',input=(self.run/'briefs.jsonl').read_text())
            self.assertNotEqual(p.returncode,0); self.assertIn(fragment,p.stderr)
        self.env['PS4_TEST_MODEL_MODE']='valid'
        p=self.call('content/write_articles.sh','replays/replay-test',input=(self.run/'briefs.jsonl').read_text())
        self.assertEqual(p.returncode,0,p.stderr)
        manifests=[json.loads(x) for x in p.stdout.splitlines()]; self.assertEqual(len(manifests),3)
        for m in manifests:
            text=(self.root/m['path']).read_text()
            self.assertIn(m['claim_ids'][0],text); self.assertTrue(any(i['url'] in text for i in self.items))

    def test_no_args_run_uses_utc_unique_snapshots_and_saves_summary_on_workflow_failure(self):
        (self.root/'config/project.json').write_text(json.dumps({'publication_name':'Replay only','topic':'fictional replay','audience':'test readers','central_question':'What do fictional records show?'}))
        sources=[{'source_id':'replay-'+k,'publisher_id':'fictional-'+k,'kind':k,'url':'https://fixture.invalid/'+k} for k in ('feed','youtube','podcast')]
        (self.root/'config/sources.json').write_text(json.dumps(sources))
        for path in self.root.glob('prompts/*.md'): path.write_text('Fictional replay test prompt only.\n')
        (self.root/'config/editorial_policy.md').write_text('Fictional replay policy only.\n')
        for path in ('collectors/fetch_feeds.sh','collectors/fetch_youtube.sh','collectors/fetch_podcasts.sh'):
            (self.root/path).write_text('#!/usr/bin/env bash\n# Replay-only stub: no network access and no collected evidence.\nexit 0\n')
            os.chmod(self.root/path,0o755)
        first=self.call('run.sh')
        self.assertNotEqual(first.returncode,0,'empty replay evidence should block editorial generation')
        runs=list((self.root/'runs').glob('*/run.json')); self.assertEqual(len(runs),1)
        first_meta=json.loads(runs[0].read_text()); parsed=dt.datetime.fromisoformat(first_meta['started_at'].replace('Z','+00:00'))
        self.assertEqual(parsed.utcoffset(),dt.timedelta(0)); self.assertEqual(first_meta['as_of_date'],parsed.date().isoformat())
        self.assertEqual(first_meta['mode'],'live')
        self.assertTrue((runs[0].parent/'summary.json').is_file())
        self.assertEqual(json.loads((runs[0].parent/'summary.json').read_text())['status'],'failed')
        time.sleep(1)  # run IDs are unique, while started_at is intentionally UTC-second precision.
        second=self.call('run.sh'); self.assertNotEqual(second.returncode,0)
        runs=list((self.root/'runs').glob('*/run.json')); self.assertEqual(len(runs),2)
        # These disposable no-network runs are replay demonstrations, not assignment live runs.
        for path in runs:
            replay_meta=json.loads(path.read_text()); replay_meta['mode']='replay'
            path.write_text(json.dumps(replay_meta))
        metas=[json.loads(p.read_text()) for p in runs]; self.assertEqual(len({m['run_id'] for m in metas}),2)
        self.assertTrue(all(m['mode']=='replay' for m in metas))
        latest=max(metas,key=lambda m:m['started_at']); self.assertEqual(latest['previous_run_id'],first_meta['run_id'])
        self.assertTrue(all((p.parent/'config').is_dir() and (p.parent/'prompts').is_dir() for p in runs))

    def _make_resume_run(self, as_of=None):
        """Build a disposable live-shaped run; never points at the user's run tree."""
        run = self.root/'runs'/'resume-fixture'
        run.mkdir(parents=True)
        shutil.copytree(self.root/'config',run/'config')
        shutil.copytree(self.root/'prompts',run/'prompts')
        today=dt.datetime.now(dt.timezone.utc).date()
        meta={'run_id':'resume-fixture','started_at':dt.datetime.now(dt.timezone.utc).isoformat(),
              'as_of_date':(as_of or today).isoformat(),'mode':'live'}
        (run/'run.json').write_text(json.dumps(meta))
        (run/'eligible.jsonl').write_text('{}\n')
        for name, value in (('decisions.jsonl','old decisions\n'),('briefs.jsonl','old briefs\n'),
                            ('articles.jsonl','old articles\n'),('video_scripts.jsonl','old scripts\n'),
                            ('review.json','{"passed":false}\n'),('summary.json','{"status":"failed"}\n'),
                            ('approval.json','{"review_id":"old"}\n')):
            (run/name).write_text(value)
        (run/'student_feedback_carry_forward').mkdir()
        (run/'student_feedback_carry_forward'/'manifest.json').write_text('{"fixture_snapshot":true}\n')
        (run/'selection_ai_decisions.jsonl').write_text('{"fixture_ai_decision":true}\n')
        (run/'logs').mkdir(); (run/'logs'/'prior.json').write_text('{"stage":"prior"}\n')
        (run/'model_calls').mkdir(); (run/'model_calls'/'prior.json').write_text('{"call":"prior"}\n')
        return run

    def test_same_day_resume_archives_and_runs_only_editorial_workflow(self):
        run=self._make_resume_run()
        config_before=(run/'config/ai.json').read_bytes(); prompts_before=(run/'prompts/select_items.md').read_bytes()
        self.write_jsonl(run/'eligible.jsonl',[{'item_id':'fixture'}])
        marker=self.root/'tests'/'resume-workflow-called'
        (self.root/'workflows/create_series.sh').write_text(
            '#!/usr/bin/env bash\n# Replay stub, no inference or network.\nprintf called > '+repr(str(marker))+'\nprintf "new decisions\\n" > "$1/decisions.jsonl"\nexit 1\n')
        os.chmod(self.root/'workflows/create_series.sh',0o755)
        for p in ('collectors/fetch_feeds.sh','collectors/fetch_youtube.sh','collectors/fetch_podcasts.sh'):
            (self.root/p).write_text('#!/usr/bin/env bash\nprintf collector-called > '+repr(str(self.root/'tests'/'collector-called'))+'\nexit 99\n')
        result=self.call('run.sh','--resume','runs/resume-fixture')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(marker.exists()); self.assertFalse((self.root/'tests'/'collector-called').exists())
        self.assertEqual((run/'config/ai.json').read_bytes(),config_before)
        self.assertEqual((run/'prompts/select_items.md').read_bytes(),prompts_before)
        self.assertEqual((run/'decisions.jsonl').read_text(),'new decisions\n')
        self.assertFalse((run/'approval.json').exists())
        self.assertTrue((run/'summary.json').is_file())
        attempts=list((run/'attempts').glob('resume-*')); self.assertEqual(len(attempts),1)
        old=attempts[0]/'pre_resume'
        for name, expected in (('run.json','live'),('decisions.jsonl','old decisions'),
                               ('review.json','false'),('summary.json','failed'),('approval.json','old')):
            self.assertIn(expected,(old/name).read_text())
        self.assertTrue((old/'logs/prior.json').is_file()); self.assertTrue((old/'model_calls/prior.json').is_file())
        self.assertTrue((old/'student_feedback_carry_forward'/'manifest.json').is_file())
        self.assertTrue((old/'selection_ai_decisions.jsonl').is_file())
        info=json.loads((attempts[0]/'resume.json').read_text())
        self.assertEqual(info['operation'],'rerun create_series only; collection and extraction are not repeated')
        self.assertTrue(info['input_sha256'])
        self.assertIn('run.sh',info['implementation_sha256'])
        self.assertIn('lib/runtime.py',info['implementation_sha256'])
        receipts=[json.loads(x.read_text()) for x in (run/'logs').glob('*.json')]
        names=[x.get('stage') for x in receipts]
        self.assertIn('run:resume_snapshot',names); self.assertIn('run',names)

    def test_cross_utc_date_resume_rejected_without_mutation(self):
        today=dt.datetime.now(dt.timezone.utc).date()
        run=self._make_resume_run(today-dt.timedelta(days=1))
        original=(run/'run.json').read_bytes()
        marker=self.root/'tests'/'resume-workflow-called'
        result=self.call('run.sh','--resume','runs/resume-fixture')
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertIn('start a new live run',result.stderr)
        self.assertEqual((run/'run.json').read_bytes(),original)
        self.assertFalse(marker.exists()); self.assertFalse((run/'attempts').exists())

if __name__=='__main__': unittest.main()
