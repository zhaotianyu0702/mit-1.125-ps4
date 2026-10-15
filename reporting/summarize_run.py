#!/usr/bin/env python3
"""Summarize available run records and stage receipts without inventing missing results."""
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from common import BadInput, load_json, read_records, repo_path, stage_main
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'review'))
import check_content

def maybe_records(path):
    return read_records(path) if path.is_file() else None

def summary(run, receipt):
    meta = load_json(run / 'run.json')
    names = {'discovered': 'candidates.jsonl', 'extracted': 'items.jsonl', 'changes': 'changes.jsonl',
             'eligible': 'eligible.jsonl', 'excluded': 'exclusions.jsonl', 'decisions': 'decisions.jsonl',
             'briefs': 'briefs.jsonl', 'articles': 'articles.jsonl', 'video_scripts': 'video_scripts.jsonl'}
    data = {key: maybe_records(run / fn) for key, fn in names.items()}
    counts = {k: (len(v) if v is not None else None) for k, v in data.items()}
    if data['changes'] is None:
        for k in ('new', 'changed', 'unchanged'):
            counts[k] = None
    else:
        change_count = Counter(x.get('change') for x in data['changes'])
        for k in ('new', 'changed', 'unchanged'):
            counts[k] = change_count.get(k, 0)
    if data['decisions'] is None:
        counts.update(accepted=None, rejected=None, deferred=None)
    else:
        decision_count = Counter(x.get('decision') for x in data['decisions'])
        counts.update(accepted=decision_count.get('accept', 0), rejected=decision_count.get('reject', 0), deferred=decision_count.get('defer', 0))
    # Distinct evidence coverage is calculated from records actually present; duplicate observations remain visible.
    raw_observations = data['discovered'] if data['discovered'] is not None else (data['extracted'] or [])
    observations = data['extracted'] if data['extracted'] is not None else raw_observations
    underlying = {}
    for row in observations:
        identity = row.get('underlying_id') or row.get('item_id') or row.get('media_url') or row.get('url')
        if identity:
            underlying.setdefault(identity, row)
    raw_underlying = {x.get('underlying_id') or x.get('item_id') or x.get('media_url') or x.get('url') for x in raw_observations
                      if x.get('underlying_id') or x.get('item_id') or x.get('media_url') or x.get('url')}
    coverage = {'raw_observations': len(raw_observations) if raw_observations or data['extracted'] is not None or data['discovered'] is not None else None,
                'raw_duplicate_observations': max(0, len(raw_observations)-len(raw_underlying)) if raw_observations else (0 if data['extracted'] is not None or data['discovered'] is not None else None),
                'distinct_underlying_items': len(underlying) if observations or data['extracted'] is not None or data['discovered'] is not None else None,
                'duplicate_observations': max(0, len(observations)-len(underlying)) if observations else (0 if data['extracted'] is not None or data['discovered'] is not None else None),
                'by_kind': {}, 'independent_publishers': len({x.get('publisher_id') for x in underlying.values() if x.get('publisher_id')}) if observations else None}
    for kind in ('feed', 'youtube', 'podcast'):
        rows = [x for x in underlying.values() if x.get('kind') == kind]
        coverage['by_kind'][kind] = {'distinct_items': len(rows), 'publishers': len({x.get('publisher_id') for x in rows if x.get('publisher_id')})}
    receipts = []
    logdir = run / 'logs'
    if logdir.is_dir():
        for p in sorted(logdir.glob('*.json')):
            try:
                x = load_json(p)
                if isinstance(x, dict) and 'stage' in x:
                    x['_file'] = str(p.relative_to(run))
                    receipts.append(x)
            except BadInput:
                continue
    latest = {}
    for item in receipts:
        latest[item['stage']] = item
    failed = [r for r in receipts if r.get('status') in ('failed', 'invalid') or r.get('exit_code') not in (None, 0)]
    incomplete = [stage for stage, r in latest.items() if r.get('status') in ('failed', 'invalid')]
    elapsed = None
    try:
        start = dt.datetime.fromisoformat(meta['started_at'].replace('Z', '+00:00'))
        finishes = [dt.datetime.fromisoformat(r['finished_at'].replace('Z', '+00:00')) for r in latest.values() if r.get('finished_at')]
        end = max(finishes) if finishes else dt.datetime.now(dt.timezone.utc)
        elapsed = max(0, int((end-start).total_seconds()))
    except (KeyError, TypeError, ValueError):
        pass
    operational_receipts = [r for r in receipts if not str(r.get('stage', '')).startswith('reporting/summarize_run')]
    measured_costs = [r for r in operational_receipts if isinstance(r.get('cost_usd'), (int, float)) and not r.get('cost_is_estimate')]
    estimated_costs = [r for r in operational_receipts if isinstance(r.get('cost_usd'), (int, float)) and r.get('cost_is_estimate')]
    known_cost = sum(float(r['cost_usd']) for r in measured_costs)
    estimated_cost = sum(float(r['cost_usd']) for r in estimated_costs)
    unknown_costs = sum(1 for r in operational_receipts if r.get('cost_usd') is None)
    tool_counts = Counter(t for r in operational_receipts for t in (r.get('tools') or []))
    required_artifacts = ['candidates/feeds.jsonl', 'candidates/youtube.jsonl', 'candidates/podcasts.jsonl', 'candidates.jsonl',
                          'items.jsonl', 'changes.jsonl', 'eligible.jsonl', 'exclusions.jsonl', 'decisions.jsonl',
                          'briefs.jsonl', 'articles.jsonl', 'video_scripts.jsonl', 'review.json']
    missing_artifacts = [name for name in required_artifacts if not (run / name).is_file()]
    expected_stages = ['collectors/fetch_feeds', 'collectors/fetch_youtube', 'collectors/fetch_podcasts',
                       'processing/extract_content', 'data/store:upsert', 'data/store:list',
                       'processing/filter_items', 'editorial/select_items', 'editorial/create_briefs',
                       'content/write_articles', 'content/write_video_scripts', 'review/check_content']
    missing_stages = [name for name in expected_stages if name not in latest]
    status = 'failed' if missing_artifacts or missing_stages or any(r.get('status') in ('failed', 'invalid') for r in latest.values()) else 'awaiting_review'
    review_path = run / 'review.json'
    approval_path = run / 'approval.json'
    review = load_json(review_path) if review_path.is_file() else None
    approval = load_json(approval_path) if approval_path.is_file() else None
    current_review = None
    if review is not None:
        class QuietReceipt: input_count = output_count = None
        try:
            current_review = check_content.assess(run, QuietReceipt(), write=False, emit=False)
        except Exception:
            current_review = None
    package_manifest_path = run / 'package/manifest.json'
    package_manifest = load_json(package_manifest_path) if package_manifest_path.is_file() else None
    package_assets = package_manifest.get('assets', []) if package_manifest else []
    package_types = {x.get('type') for x in package_assets}
    required_package_types = {'article', 'video_script', 'source_notes', 'publication_links'}
    package_complete = bool(package_manifest and current_review and package_manifest.get('review_id') == current_review.get('review_id')
                            and required_package_types <= package_types
                            and all((run / a.get('path', '')).is_file() for a in package_assets))
    approval_current = bool(current_review and approval and approval.get('decision') == 'approve'
                            and approval.get('review_id') == current_review.get('review_id'))
    if status != 'failed' and current_review and current_review.get('passed') and approval_current and package_complete:
        status = 'ready_for_production'
    elif status != 'failed' and current_review and not current_review.get('passed'):
        status = 'failed'
    links_path = run / 'package/publication_links.json'
    if not links_path.is_file():
        links_path = run / 'publication_links.json'
    links = load_json(links_path) if links_path.is_file() else None
    result = {'run_id': meta.get('run_id'), 'status': status, 'as_of_date': meta.get('as_of_date'), 'counts': counts,
              'source_coverage': coverage, 'stages': {'latest_receipts': list(latest.values()), 'historical_failures': failed,
                  'incomplete_stages': incomplete, 'missing_required_artifacts': missing_artifacts,
                  'missing_required_stages': missing_stages,
                  'failed_or_incomplete': bool(incomplete or missing_artifacts or missing_stages)},
              'elapsed_seconds': elapsed, 'tools': dict(tool_counts),
              'costs': {'known_usd': round(known_cost, 6) if measured_costs else None,
                        'estimated_usd': round(estimated_cost, 6) if estimated_costs else None, 'unknown_cost_receipts': unknown_costs},
              'review': {'present': review is not None, 'passed': review.get('passed') if review else None,
                         'approval_present': approval is not None, 'approval_matches': approval_current,
                         'current_review_passed': current_review.get('passed') if current_review else None,
                         'package_matches_current_review': package_complete},
              'publication_links': links,
              'remaining_manual_actions': (['Human editorial review and approval.'] if status == 'awaiting_review' else []) +
                  ['Render and verify three videos in Google Vids or HeyGen.', 'Publish three Substack articles and three YouTube videos.',
                   'Add article and evidence links to video descriptions and record publication URLs.'],
              'interpretation': 'Missing artifact counts are null; zero means the relevant artifact exists and contains no records.'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    receipt.input_count = sum(v is not None for v in data.values())
    receipt.output_count = 1
    return 0

if __name__ == '__main__':
    raise SystemExit(stage_main('reporting/summarize_run', summary))
