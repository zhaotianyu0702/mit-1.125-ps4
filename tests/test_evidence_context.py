"""Synthetic source-context tests. No live evidence or model calls."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'editorial'))
import evidence

class ContextTests(unittest.TestCase):
    def test_long_media_keeps_exact_segments_and_declares_sampling(self):
        with tempfile.TemporaryDirectory() as tmp:
            text, seg = Path(tmp)/'text.txt', Path(tmp)/'segments.json'
            segments = [{'segment_id': f's-{i}', 'start_seconds': i*10, 'end_seconds': (i+1)*10,
                         'text': ('Testing agent reliability. ' if i % 2 else 'Other topic. ') * 30} for i in range(40)]
            text.write_text('\n'.join(s['text'] for s in segments))
            seg.write_text(json.dumps(segments))
            item = dict(item_id='synthetic',version_id='v1',title='Fictional source',publisher_id='fictional',
                        kind='podcast',url='https://fictional.example',published_at='2026-10-08T00:00:00Z',
                        text_path='text.txt',segments_path='segments.json')
            with patch.object(evidence,'repo_path',side_effect=lambda p:Path(tmp)/p):
                context=evidence.context(item,budget=3500)
            self.assertEqual(context['context_scope']['mode'],'sampled_passages')
            self.assertIn('Do not infer absence',context['context_scope']['limitation'])
            self.assertIsNone(context['text'])
            self.assertLess(len(context['segments']),len(segments))
            self.assertTrue(all(s in segments for s in context['segments']))
            self.assertLessEqual(sum(len(s['text'])for s in context['segments']),3500)

if __name__=='__main__':unittest.main()
