#!/usr/bin/env python3
"""Assemble a production handoff after a fresh machine and human review."""
import json
import contextlib
import io
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from common import BadInput, Receipt, load_json, read_records, repo_path, stage_main, write_json
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'review'))
import check_content

class QuietReceipt:
    input_count = output_count = None

def merge_publication_links(previous):
    old = {str(x.get('piece_id')): x for x in previous if isinstance(x, dict)} if isinstance(previous, list) else {}
    return [{'piece_id': pid, 'substack_url': old.get(pid, {}).get('substack_url'),
             'youtube_url': old.get(pid, {}).get('youtube_url')} for pid in ('01', '02', '03')]

def package(run, receipt):
    review_path, approval_path = run / 'review.json', run / 'approval.json'
    problems = []
    if not approval_path.is_file():
        problems.append('human approval is missing')
    if not review_path.is_file():
        problems.append('review is missing')
    if problems:
        raise RuntimeError('; '.join(problems))
    review = load_json(review_path)
    approval = load_json(approval_path)
    # A fresh assessment catches edits to drafts or referenced evidence since prior review.
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            check_content.assess(run, QuietReceipt())
    except Exception as exc:
        raise RuntimeError(f'content recheck could not complete: {exc}') from exc
    current = load_json(review_path)
    problems = []
    if not current.get('passed'):
        problems.append('current content review has blocking errors')
    if review.get('review_id') != current.get('review_id'):
        problems.append('saved review is stale; rerun and inspect the current review')
    if approval.get('review_id') != current.get('review_id'):
        problems.append('approval does not match the current review')
    if approval.get('decision') != 'approve':
        problems.append('human approval decision is not approve')
    if not isinstance(approval.get('reviewer'), str) or not approval['reviewer'].strip():
        problems.append('approval has no reviewer')
    if problems:
        raise RuntimeError('; '.join(problems))
    briefs = {str(x['piece_id']): x for x in read_records(run / 'briefs.jsonl')}
    article_records = {str(x['piece_id']): x for x in read_records(run / 'articles.jsonl')}
    script_records = {str(x['piece_id']): x for x in read_records(run / 'video_scripts.jsonl')}
    out = run / 'package'
    out.mkdir(parents=True, exist_ok=True)
    assets, files = [], {}
    for pid in ('01', '02', '03'):
        if pid not in briefs or pid not in article_records or pid not in script_records:
            raise RuntimeError(f'piece {pid} is missing from a reviewed manifest')
        targets = [('articles', article_records[pid]), ('video_scripts', script_records[pid])]
        for folder, record in targets:
            src = repo_path(record['path'])
            dest = out / folder / f'{pid}.md'
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            assets.append({'piece_id': pid, 'type': 'article' if folder == 'articles' else 'video_script', 'path': str(dest.relative_to(run))})
        source_notes = out / 'sources' / f'{pid}.md'
        source_notes.parent.mkdir(parents=True, exist_ok=True)
        rows = [f"# Sources for {pid}: {briefs[pid].get('title', '')}", '',
                'These notes are for publication handoff. Verify sources and retain timestamp or passage context in the published copy.', '']
        for claim in briefs[pid].get('claims', []):
            rows.append(f"## {claim.get('claim_id', '')}: {claim.get('statement', '')}")
            for ref in claim.get('evidence', []):
                e = check_content.get_evidence(ref['item_id'], ref['version_id'])
                if e is None:
                    raise RuntimeError(f"source evidence disappeared: {ref['item_id']}@{ref['version_id']}")
                loc = ref.get('locator', {})
                description = loc.get('quote') if loc.get('type') == 'text' else f"segment {loc.get('segment_id')}"
                rows.append(f"- {e.get('publisher_id')} — [{e.get('title')}]({e.get('url')}); {description}")
            rows.append('')
        source_notes.write_text('\n'.join(rows), encoding='utf-8')
        assets.append({'piece_id': pid, 'type': 'source_notes', 'path': str(source_notes.relative_to(run))})
    links_path = out / 'publication_links.json'
    existing_path = run / 'publication_links.json'
    prior = links_path if links_path.is_file() else existing_path
    old_data = []
    if prior.is_file():
        data = load_json(prior)
        old_data = data if isinstance(data, list) else []
    links = merge_publication_links(old_data)
    write_json(links_path, links)
    assets.append({'piece_id': None, 'type': 'publication_links', 'path': str(links_path.relative_to(run))})
    manifest = {'review_id': current['review_id'], 'assets': assets,
                'manual_actions': ['Render and quality-check each video in Google Vids or HeyGen.',
                                   'Publish each article on Substack with shareable access.',
                                   'Publish each video on YouTube and add article and source links to its description.',
                                   'Enter the resulting Substack and YouTube URLs in publication_links.json.'],
                'published': False}
    write_json(out / 'manifest.json', manifest)
    receipt.input_count = 3
    receipt.output_count = len(assets) + 1
    print(json.dumps(manifest, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    # Packaging precondition failures are expected incomplete handoffs (exit 1).
    try:
        raise SystemExit(stage_main('publishing/prepare_package', package))
    except SystemExit:
        raise
