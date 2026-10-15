import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[1]

class StoreFilterContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ps4-store-filter-')
        self.root=Path(self.tmp.name)/'ps4'
        shutil.copytree(SOURCE,self.root,ignore=shutil.ignore_patterns('.git','__pycache__','store.sqlite3','runs','evidence','media','assets','docs'))
        self.env=dict(os.environ); self.env['PS4_RUN_DIR']='runs/store-tests'
        (self.root/'runs/store-tests').mkdir(parents=True)
        (self.root/'runs/store-tests/run.json').write_text(json.dumps({'run_id':'test-run','as_of_date':'2026-10-08'}))
    def tearDown(self): self.tmp.cleanup()
    def call(self,script,*args,input=None):
        return subprocess.run(['bash',str(self.root/script),*args],cwd=self.root,env=self.env,input=input,text=True,capture_output=True)
    def test_example_store_replay_dedupe_versions_and_atomic_validation(self):
        self.assertEqual(self.call('data/store.sh','init').returncode,0)
        empty=self.call('data/store.sh','list')
        self.assertEqual((empty.returncode,empty.stdout),(0,''))
        first=self.call('data/store.sh','upsert','runs/store-tests',input=(self.root/'examples/items.jsonl').read_text())
        self.assertEqual(first.returncode,0,first.stderr)
        initial=[json.loads(x) for x in first.stdout.splitlines()]
        expected=[json.loads(x) for x in (self.root/'examples/initial_changes_expected.jsonl').read_text().splitlines()]
        self.assertEqual(initial,expected)
        replay=self.call('data/store.sh','upsert','runs/store-tests',input=(self.root/'examples/replay_items.jsonl').read_text())
        self.assertEqual(replay.returncode,0,replay.stderr)
        self.assertEqual([json.loads(x) for x in replay.stdout.splitlines()],[json.loads(x) for x in (self.root/'examples/replay_changes_expected.jsonl').read_text().splitlines()])
        all_items=[json.loads(x) for x in self.call('data/store.sh','list').stdout.splitlines()]
        self.assertEqual(len(all_items),3)
        pid='podcast:fictional-episode'; old='8f4fc03210022af1be3798fa7355ae3fa40297873b3ed037420ded36c5849bd5'
        self.assertEqual(json.loads(self.call('data/store.sh','get',pid,old).stdout)['version_id'],old)
        missing=self.call('data/store.sh','get','missing')
        self.assertEqual(missing.returncode,1)
        self.assertIn('not found',missing.stderr)
        old_record=next(json.loads(x) for x in (self.root/'examples/items.jsonl').read_text().splitlines() if json.loads(x)['item_id']==pid)
        revert=self.call('data/store.sh','upsert','runs/store-tests',input=json.dumps(old_record)+'\n')
        self.assertEqual(revert.returncode,0,revert.stderr)
        self.assertEqual(json.loads(revert.stdout)['change'],'changed')
        current=json.loads(next(x for x in self.call('data/store.sh','list').stdout.splitlines() if json.loads(x)['item_id']==pid))
        self.assertEqual(current['version_id'],old)
        self.assertEqual(json.loads(self.call('data/store.sh','get',pid).stdout),current)
        # Raw media download paths may change while normalized version identity/content stays fixed.
        relocated=dict(old_record,media_path='data/media/second-raw-copy.mp3')
        relocated_result=self.call('data/store.sh','upsert','runs/store-tests',input=json.dumps(relocated)+'\n')
        self.assertEqual(relocated_result.returncode,0,relocated_result.stderr)
        self.assertEqual(json.loads(relocated_result.stdout)['change'],'unchanged')
        precision_only=dict(old_record,publication_precision='day',source_date_field='datePublished')
        precision_result=self.call('data/store.sh','upsert','runs/store-tests',input=json.dumps(precision_only)+'\n')
        self.assertEqual(precision_result.returncode,0,precision_result.stderr)
        self.assertEqual(json.loads(precision_result.stdout)['change'],'unchanged')
        changed_date=dict(old_record,published_at='2026-10-04T09:00:00Z',publication_precision='day',source_date_field='datePublished')
        date_collision=self.call('data/store.sh','upsert','runs/store-tests',input=json.dumps(changed_date)+'\n')
        self.assertEqual(date_collision.returncode,2)
        self.assertIn('collision',date_collision.stderr.lower())
        collision=dict(old_record,title='Different evidence with same version ID')
        rejected_collision=self.call('data/store.sh','upsert','runs/store-tests',input=json.dumps(collision)+'\n')
        self.assertEqual(rejected_collision.returncode,2)
        self.assertIn('collision',rejected_collision.stderr.lower())
        logs=list((self.root/'runs/store-tests/logs').glob('*.json'))
        stages={json.loads(p.read_text())['stage'] for p in logs}
        self.assertIn('data/store:list',stages)
        self.assertIn('data/store:get',stages)
        self.assertIn('data/store:upsert',stages)
        before=self.call('data/store.sh','list').stdout
        malformed=json.dumps({'item_id':'bad'})+'\n'
        rejected=self.call('data/store.sh','upsert','runs/store-tests',input=malformed)
        self.assertEqual(rejected.returncode,2)
        self.assertEqual(before,self.call('data/store.sh','list').stdout)
    def test_example_date_boundaries_and_reasons(self):
        inp=(self.root/'examples/filter_input.jsonl').read_text()
        res=self.call('processing/filter_items.sh','runs/store-tests',input=inp)
        self.assertEqual(res.returncode,0,res.stderr)
        expected=json.loads((self.root/'examples/filter_expected.json').read_text())
        eligible={json.loads(x)['item_id'] for x in res.stdout.splitlines()}
        self.assertEqual(eligible,set(expected['eligible_item_ids']))
        exclusions=[json.loads(x) for x in (self.root/'runs/store-tests/exclusions.jsonl').read_text().splitlines()]
        self.assertEqual({x['item_id']:x['reason'] for x in exclusions},{x['item_id']:x['reason'] for x in expected['exclusions']})

if __name__=='__main__': unittest.main()
