#!/usr/bin/env python3
"""Content component: render each accepted brief through the configured model."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'editorial'))
from common import BadInput, atomic_write, emit, load_json, read_jsonl, relative, repo_path, stage_main
from model import infer_validated
from evidence import context, get_version, validate_briefs

def generate(run, receipt, kind):
    briefs = read_jsonl(sys.stdin)
    receipt.input_count = len(briefs)
    versions = {}
    for brief in briefs:
        for claim in brief.get('claims', []):
            for ref in claim.get('evidence', []):
                key = (ref['item_id'], ref['version_id'])
                if key not in versions:
                    versions[key] = get_version(run, *key)
    validate_briefs(briefs, list(versions.values()))
    instruction = (run / 'prompts' / ('write_' + kind + '.md')).read_text()
    manifests = []
    for brief in briefs:
        keys = {(e['item_id'], e['version_id']) for c in brief['claims'] for e in c['evidence']}
        items = [versions[k] for k in sorted(keys)]
        date = load_json(run / 'run.json')['as_of_date']
        ids = [c['claim_id'] for c in brief['claims']]
        def validate_response(response):
            text = response.get('markdown') if isinstance(response, dict) else None
            if not isinstance(text, str) or len(text) < 200 or date not in text:
                raise BadInput('Model draft missing substantive Markdown or as-of date')
            missing_ids = [cid for cid in ids if cid not in text]
            if missing_ids:
                raise BadInput('Model draft omitted required claim marker(s): ' + ', '.join(missing_ids))
            if not any(i['url'] in text for i in items):
                raise BadInput('Model draft omitted audience-readable source links')
            return response
        response = infer_validated(
            run, receipt, 'write_' + kind, instruction,
            {'brief': brief, 'project': load_json(run / 'config/project.json'),
             'as_of_date': date, 'items': [context(i) for i in items]},
            {'markdown': 'complete draft with as-of date, all claim markers, audience-readable citations and source notes'},
            validate_response)
        text = response['markdown']
        # Deterministic source notes keep every evidence locator inspectable for the human reviewer.
        notes = ['\n\n## Evidence notes (for editorial review)\n']
        for claim in brief['claims']:
            notes.append(f"\n- **{claim['claim_id']} ({claim['type']})**: {claim['statement']}")
            for ref in claim['evidence']:
                item = versions[(ref['item_id'], ref['version_id'])]
                loc = ref['locator']
                if loc['type'] == 'text':
                    notes.append(f"  - [{item['title']}]({item['url']}), version `{item['version_id']}`; exact passage: {loc['quote']}")
                else:
                    seg = next(s for s in load_json(repo_path(item['segments_path'])) if s['segment_id'] == loc['segment_id'])
                    sec = int(seg['start_seconds'])
                    anchor = ('&t=' if '?' in item['url'] else '?t=') + str(sec) + 's' if item['kind'] == 'youtube' else '#t=' + str(sec)
                    notes.append(f"  - [{item['title']} · {sec//60}:{sec%60:02d}]({item['url']}{anchor}), segment `{seg['segment_id']}`, version `{item['version_id']}`.")
        path = run / kind / (brief['piece_id'] + '.md')
        atomic_write(path, text.rstrip() + '\n'.join(notes) + '\n')
        manifests.append({'piece_id': brief['piece_id'], 'path': relative(path), 'claim_ids': ids})
    receipt.output_count = len(manifests)
    emit(manifests)

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in ('articles', 'video_scripts'):
        print('Usage: generate.py articles|video_scripts RUN_DIR', file=sys.stderr)
        sys.exit(2)
    kind = sys.argv.pop(1)
    raise SystemExit(stage_main('content/write_' + kind, lambda r, s: generate(r, s, kind)))
