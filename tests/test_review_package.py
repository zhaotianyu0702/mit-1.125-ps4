"""Clearly labeled synthetic replay tests; all run data is temporary and fixture-only."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_package', ROOT / 'publishing/prepare_package.py')
package_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_module)
review_module = package_module.check_content

def write_jsonl(path, records):
    path.write_text(''.join(json.dumps(x) + '\n' for x in records), encoding='utf-8')

class ReviewPackageReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.review-package-fixture-replay-', dir=ROOT)
        self.run = Path(self.tmp.name) / 'fixture-replay'
        self.run.mkdir()
        (self.run / 'run.json').write_text(json.dumps({'run_id':'fixture-replay', 'started_at':'2026-10-12T00:00:00Z', 'as_of_date':'2026-10-12', 'mode':'replay', 'previous_run_id':None}))
        self.original_get = review_module.get_evidence
        self.evidence = {}
        review_module.get_evidence = lambda item_id, version_id: self.evidence.get((item_id, version_id))

    def tearDown(self):
        review_module.get_evidence = self.original_get
        self.tmp.cleanup()

    def assess(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return review_module.assess(self.run, SimpleNamespace(input_count=None, output_count=None), write=False, emit=False)

    def make_valid_fixture(self):
        asof = '2026-10-12'
        eligible = []
        refs_by_kind = {}
        # Twelve unique items across all required kinds and six independent publishers.
        for index in range(12):
            kind = ('feed', 'youtube', 'podcast')[index // 4]
            publisher = f'publisher-{index % 6 + 1}'
            item_id = f'{kind}:fixture-{index:02d}'
            version_id = f'v{index:02d}'
            underlying = f'underlying-{index:02d}'
            url = f'https://source.example/{index:02d}'
            date = '2026-09-12T23:30:00-02:00' if index == 0 else '2026-10-05T12:00:00Z'
            item = {'item_id':item_id, 'underlying_id':underlying, 'version_id':version_id, 'publisher_id':publisher,
                    'kind':kind, 'title':f'Fixture source {index}', 'published_at':date, 'url':url,
                    'media_url':None if kind == 'feed' else url + '/media'}
            eligible.append(item)
            if index in (0, 4, 8):
                evidence_item = dict(item)
                if kind == 'feed':
                    asset = self.run / 'assets' / f'{index}.txt'
                    asset.parent.mkdir(exist_ok=True)
                    quote = f'Exact fixture passage {index}.'
                    asset.write_text(quote, encoding='utf-8')
                    evidence_item['text_path'] = str(asset.relative_to(ROOT))
                    evidence_item['segments_path'] = None
                    locator = {'type':'text', 'quote':quote}
                else:
                    asset = self.run / 'assets' / f'{index}.json'
                    quote = f'Spoken fixture passage {index}.'
                    asset.write_text(json.dumps([{'segment_id':f's{index}', 'start_seconds':1.0, 'end_seconds':2.0, 'text':quote}]), encoding='utf-8')
                    evidence_item['segments_path'] = str(asset.relative_to(ROOT))
                    evidence_item['text_path'] = None
                    locator = {'type':'segment', 'segment_id':f's{index}'}
                self.evidence[(item_id, version_id)] = evidence_item
                refs_by_kind[kind] = {'item_id':item_id, 'version_id':version_id, 'locator':locator}
        # One raw duplicate proves coverage keys on underlying_id, not observation count or URL.
        duplicate = dict(eligible[0], item_id='rss-copy:fixture-duplicate', url='https://other.example/duplicate')
        eligible.append(duplicate)
        write_jsonl(self.run / 'eligible.jsonl', eligible)
        briefs, articles, scripts = [], [], []
        for n, pid in enumerate(('01','02','03'), 1):
            claims = []
            claim_ids = []
            for j, kind in enumerate(('feed','youtube','podcast'), 1):
                cid = f'{pid}-c{j}'
                claim_ids.append(cid)
                claims.append({'claim_id':cid, 'statement':f'Fixture claim {pid}-{j}', 'type':'reported_fact', 'evidence':[refs_by_kind[kind]]})
            briefs.append({'piece_id':pid, 'title':f'Fixture title {pid}', 'question':'Fixture question', 'argument':f'Fixture argument {pid}',
                           'synthesis':'Fixture synthesis connects the sources.', 'limitations':'Fixture limitation.', 'claims':claims})
            for folder, records in (('articles', articles), ('video_scripts', scripts)):
                draft = self.run / folder / f'{pid}.md'
                draft.parent.mkdir(exist_ok=True)
                urls = ' '.join(self.evidence[(refs_by_kind[k]['item_id'], refs_by_kind[k]['version_id'])]['url'] for k in ('feed','youtube','podcast'))
                draft.write_text(f'# Fixture {pid}\nAs of {asof}. {urls} ' + ' '.join(claim_ids), encoding='utf-8')
                records.append({'piece_id':pid, 'path':str(draft.relative_to(ROOT)), 'claim_ids':claim_ids})
        write_jsonl(self.run / 'briefs.jsonl', briefs)
        write_jsonl(self.run / 'articles.jsonl', articles)
        write_jsonl(self.run / 'video_scripts.jsonl', scripts)

    def test_missing_files_assess_false_with_stdout_and_summary_fails(self):
        import subprocess
        proc = subprocess.run(['bash', str(ROOT/'review/check_content.sh'), str(self.run)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        review = json.loads(proc.stdout)
        self.assertFalse(review['passed'])
        summary = subprocess.run(['bash', str(ROOT/'reporting/summarize_run.sh'), str(self.run)], capture_output=True, text=True)
        self.assertEqual(json.loads(summary.stdout)['status'], 'failed')

    def test_valid_fixture_passes_utc_boundary_and_underlying_dedup(self):
        self.make_valid_fixture()
        result = self.assess()
        self.assertTrue(result['passed'], result['issues'])
        # Twelve raw rows but only eleven underlying IDs must fail the corpus minimum.
        eligible = [json.loads(x) for x in (self.run/'eligible.jsonl').read_text().splitlines()]
        eligible.pop(-2)
        write_jsonl(self.run/'eligible.jsonl', eligible)
        result = self.assess()
        self.assertFalse(result['passed'])
        self.assertTrue(any('11 distinct underlying items' in x['message'] for x in result['issues']))

    def test_word_counts_exclude_appended_notes_and_visual_directions(self):
        self.make_valid_fixture()
        article_path = self.run / 'articles/01.md'
        script_path = self.run / 'video_scripts/01.md'
        cited = [self.evidence[(f'{kind}:fixture-{index:02d}', f'v{index:02d}')]['url']
                 for kind,index in (('feed',0),('youtube',4),('podcast',8))]
        urls = ' '.join(cited)
        markers = '[01-c1] [01-c2] [01-c3]'
        article_path.write_text(
            f'As of 2026-10-12 {urls} {markers} body words\n\n'
            '## Evidence notes (for editorial review)\n' + 'reference-only-token ' * 1000,
            encoding='utf-8')
        script_path.write_text(
            f'As of 2026-10-12 {urls} {markers}\n\n'
            '## Narration\nspoken words one two three four [01-c1] [01-c2] [01-c3]\n\n'
            '## Visual direction\n' + 'paint-camera-transition ' * 1000 + '\n\n'
            '## Evidence notes\n' + 'reference-only-token ' * 1000,
            encoding='utf-8')
        result = self.assess()
        article_warning = next(x['message'] for x in result['issues'] if x.get('piece_id') == '01' and x['artifact'] == 'articles/01')
        script_warning = next(x['message'] for x in result['issues'] if x.get('piece_id') == '01' and x['artifact'] == 'video_scripts/01')
        self.assertEqual(article_warning, 'Article is approximately 11 words; target is 600–900')
        self.assertEqual(script_warning, 'Narration is approximately 6 spoken words; target is 390–750')
        self.assertTrue(any(x.get('piece_id') == '02' and x['artifact'] == 'video_scripts/02' and 'Could not isolate labeled Narration' in x['message'] for x in result['issues']))

    def test_asset_or_draft_change_invalidates_approval_and_package(self):
        self.make_valid_fixture()
        result = self.assess()
        self.assertTrue(result['passed'], result['issues'])
        (self.run / 'review.json').write_text(json.dumps(result), encoding='utf-8')
        (self.run / 'approval.json').write_text(json.dumps({'review_id':result['review_id'], 'decision':'approve', 'reviewer':'fixture student', 'reviewed_at':'fixture-only', 'notes':'synthetic'}))
        with contextlib.redirect_stdout(io.StringIO()):
            package_module.package(self.run, SimpleNamespace(input_count=None, output_count=None))
        manifest = json.loads((self.run/'package/manifest.json').read_text())
        self.assertEqual(manifest['review_id'], result['review_id'])
        # A retained asset edit and draft edit each alter current fingerprint; stale approval cannot repackage.
        text_path = next((self.run/'assets').glob('*.txt'))
        text_path.write_text('changed fixture passage', encoding='utf-8')
        changed = self.assess()
        self.assertNotEqual(result['review_id'], changed['review_id'])
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                package_module.package(self.run, SimpleNamespace(input_count=None, output_count=None))
        self.assertFalse(changed['passed'])
        # Repair the asset, re-review and re-approve; a subsequent draft edit also blocks packaging.
        text_path.write_text('Exact fixture passage 0.', encoding='utf-8')
        repaired = self.assess()
        self.assertTrue(repaired['passed'], repaired['issues'])
        (self.run/'review.json').write_text(json.dumps(repaired), encoding='utf-8')
        (self.run/'approval.json').write_text(json.dumps({'review_id':repaired['review_id'], 'decision':'approve', 'reviewer':'fixture student'}))
        article_path = self.run/'articles/01.md'
        article_path.write_text(article_path.read_text() + ' changed draft', encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                package_module.package(self.run, SimpleNamespace(input_count=None, output_count=None))

    def test_repackage_preserves_entered_links(self):
        links = package_module.merge_publication_links([
            {'piece_id':'01', 'substack_url':'https://example.test/a', 'youtube_url':None},
            {'piece_id':'02', 'substack_url':None, 'youtube_url':'https://example.test/b'}])
        self.assertEqual(links[0]['substack_url'], 'https://example.test/a')
        self.assertEqual(links[1]['youtube_url'], 'https://example.test/b')

if __name__ == '__main__':
    unittest.main()
