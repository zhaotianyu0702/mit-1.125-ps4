"""Editorial evidence context and reference validation, using the store's public API."""
import json
import os
import re
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from common import ROOT, BadInput, load_json, repo_path

def context(item, budget=18000):
    value = {k: item[k] for k in ('item_id', 'version_id', 'title', 'publisher_id', 'kind', 'url', 'published_at')}
    value['underlying_id'] = item.get('underlying_id', item['item_id'])
    text = repo_path(item['text_path']).read_text()
    segments = load_json(repo_path(item['segments_path'])) if item.get('segments_path') else None
    # Bounded, inspectable retrieval for long recordings. Never pretend an excerpt is a full read.
    blocks = segments if segments is not None else [p for p in text.split('\n') if p.strip()]
    texts = [b['text'] if isinstance(b, dict) else b for b in blocks]
    if sum(map(len, texts)) <= budget:
        chosen = list(range(len(blocks)))
    else:
        keywords = re.compile(r'\b(test\w*|review\w*|evaluat\w*|benchmark\w*|cost\w*|budget\w*|reliab\w*|cod\w*|agent\w*|deploy\w*|fail\w*)\b', re.I)
        # Include the opening and evenly distributed timeline anchors, then relevant passages.
        anchors = sorted({0, *[int(n * (len(blocks) - 1) / 9) for n in range(10)]})
        ranked = sorted(range(len(blocks)), key=lambda n: (-len(keywords.findall(texts[n])), n))
        chosen, used = [], 0
        for n in anchors + ranked:
            if n not in chosen and used + len(texts[n]) <= budget:
                chosen.append(n)
                used += len(texts[n])
        chosen.sort()
    sampled = len(chosen) < len(blocks)
    value['context_scope'] = {'mode': 'sampled_passages' if sampled else 'full_retained_text',
                              'included_blocks': len(chosen), 'total_blocks': len(blocks),
                              'original_text_characters': len(text), 'budget_characters': budget,
                              'method': 'opening + timeline-spread anchors + coding/review/evaluation keyword ranking',
                              'limitation': 'Do not infer absence or claim the entire source was reviewed from sampled passages. Defer if these passages cannot justify a decision.' if sampled else None}
    value['segments'] = [segments[n] for n in chosen] if segments is not None else None
    value['text'] = None if segments is not None else '\n\n[passage boundary]\n\n'.join(texts[n] for n in chosen)
    return value

def get_version(run, item_id, version_id):
    env = dict(os.environ, PS4_RUN_DIR=str(run))
    proc = subprocess.run(['bash', str(ROOT / 'data/store.sh'), 'get', item_id, version_id], capture_output=True, text=True, env=env)
    if proc.returncode:
        raise BadInput(f'Unknown source version {item_id}@{version_id}')
    return json.loads(proc.stdout)

def validate_briefs(briefs, items, expected_piece_ids=('01', '02', '03')):
    expected = set(expected_piece_ids)
    if not isinstance(briefs, list) or len(briefs) != len(expected) or {b.get('piece_id') for b in briefs} != expected:
        raise BadInput('Model must return exactly briefs ' + ', '.join(sorted(expected)))
    if len({b.get('argument') for b in briefs}) != len(expected):
        raise BadInput('Brief arguments must be distinct')
    # Validation always resolves against the FULL retained source, never the bounded model context.
    lookup = {(i['item_id'], i['version_id']): context(i, budget=10**12) for i in items}
    for brief in briefs:
        for k in ('title', 'question', 'argument', 'synthesis', 'limitations'):
            if not isinstance(brief.get(k), str) or not brief[k].strip():
                raise BadInput('Brief requires nonempty ' + k)
        claims = brief.get('claims')
        if not isinstance(claims, list) or not claims:
            raise BadInput('Brief requires claims')
        seen, pubs = set(), set()
        for claim in claims:
            cid = claim.get('claim_id', '')
            if not isinstance(cid, str) or not cid.startswith(brief['piece_id'] + '-c') or cid in seen:
                raise BadInput('Missing, duplicate or wrong-piece claim ID')
            seen.add(cid)
            if claim.get('type') not in ('reported_fact', 'source_claim', 'inference') or not claim.get('statement'):
                raise BadInput('Claim type/statement invalid')
            if not isinstance(claim.get('evidence'), list) or not claim['evidence']:
                raise BadInput('Every claim requires evidence')
            for ref in claim['evidence']:
                item = lookup.get((ref.get('item_id'), ref.get('version_id')))
                if item is None:
                    raise BadInput('Brief references an unaccepted or missing source version')
                loc = ref.get('locator', {})
                if item['kind'] == 'feed':
                    source_text = repo_path(next(i['text_path'] for i in items if i['item_id'] == item['item_id'] and i['version_id'] == item['version_id'])).read_text()
                    if loc.get('type') != 'text' or not loc.get('quote') or loc['quote'] not in source_text:
                        raise BadInput('Written evidence quote is not exact')
                elif loc.get('type') != 'segment' or loc.get('segment_id') not in {s['segment_id'] for s in item['segments'] or []}:
                    raise BadInput('Media evidence requires a real segment ID')
                pubs.add(item['publisher_id'])
        if len(pubs) < 3:
            raise BadInput('Each brief must cite at least three independent publishers')
    return briefs
