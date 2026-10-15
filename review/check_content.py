#!/usr/bin/env python3
"""Mechanical assessment of the current editorial run."""
import datetime as dt
import hashlib
import json
import subprocess
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from common import BadInput, Receipt, load_json, read_records, repo_path, stage_main, write_json, digest

PIECES = ('01', '02', '03')

def lines(path):
    return read_records(path) if path.is_file() else None

def count_words(text):
    return len(text.split())

ARTICLE_NOTES_HEADING = re.compile(r'(?im)^\s*#{1,6}\s*(?:evidence\s+notes|source\s+notes|references|sources)\b[^\n]*')
SCRIPT_BLOCK_LABEL = re.compile(
    r'(?im)^[ \t]*(?:#{1,6}[ \t]*)?(Narration(?:[ \t]*\([^\n)]*\))?|'
    r'Visual(?:[ \t]+directions?)?|On[ -]screen(?:[ \t]+directions?)?|'
    r'Evidence notes|Source notes|References|Sources)[ \t]*:?[ \t]*'
)
CLAIM_MARKER = re.compile(r'\[\d{2}-c\d+\]')
URL = re.compile(r'https?://\S+', re.I)

def article_body(text):
    """Exclude appended editorial/source notes from the audience-facing article count."""
    marker = ARTICLE_NOTES_HEADING.search(text)
    return text[:marker.start()] if marker else text

def narration_text(text):
    """Return spoken text from labeled narration blocks, or None when it is ambiguous."""
    labels = list(SCRIPT_BLOCK_LABEL.finditer(text))
    narration = []
    for index, label in enumerate(labels):
        if not label.group(1).casefold().startswith('narration'):
            continue
        end = labels[index + 1].start() if index + 1 < len(labels) else len(text)
        block = text[label.end():end].strip()
        if block:
            narration.append(block)
    return '\n'.join(narration) if narration else None

def spoken_word_count(text):
    """Count narration prose, excluding URLs and internal claim markers."""
    clean = URL.sub(' ', CLAIM_MARKER.sub(' ', text))
    return count_words(clean)

def parse_utc_date(value):
    if not isinstance(value, str):
        raise ValueError('date is not a string')
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('timestamp must include a timezone')
        return stamp.astimezone(dt.timezone.utc).date()

def underlying_id(item):
    return item.get('underlying_id') or item.get('item_id') or item.get('media_url') or item.get('url')

def add(issues, artifact, severity, message, piece_id=None):
    issue = {'artifact': artifact, 'severity': severity, 'message': message}
    if piece_id is not None:
        issue['piece_id'] = piece_id
    issues.append(issue)

def get_evidence(item_id, version_id):
    proc = subprocess.run(['bash', str(Path(__file__).resolve().parents[1] / 'data/store.sh'), 'get', item_id, version_id],
                          text=True, capture_output=True)
    if proc.returncode:
        return None
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None

def assess(run, receipt, write=True, emit=True):
    issues, inputs, records, assets = [], {}, {}, {}
    run_meta = load_json(run / 'run.json')
    as_of = run_meta.get('as_of_date')
    try:
        as_day = parse_utc_date(as_of)
    except (TypeError, ValueError):
        raise BadInput('run.json must contain a valid as_of_date')
    required = ['briefs.jsonl', 'articles.jsonl', 'video_scripts.jsonl']
    for name in required:
        p = run / name
        if not p.is_file():
            add(issues, name, 'error', 'Required artifact is missing')
            records[name] = None
        else:
            records[name] = lines(p)
            inputs[name] = p.read_bytes().hex()
    briefs, articles, scripts = (records[x] for x in required)
    manifests = {'articles': articles, 'video_scripts': scripts}
    expected = set(PIECES)
    for name, recs in records.items():
        if recs is not None and {str(r.get('piece_id')) for r in recs} != expected:
            add(issues, name, 'error', 'Must contain exactly one manifest/brief for each piece 01, 02, and 03')
        if recs is not None and len(recs) != 3:
            add(issues, name, 'error', 'Must contain exactly three records')
    brief_map = {str(b.get('piece_id')): b for b in briefs or []}
    titles = [str(x.get('title', '')).strip().casefold() for x in (briefs or [])]
    arguments = [str(x.get('argument', '')).strip().casefold() for x in (briefs or [])]
    if len(set(titles)) != len(titles) or len(set(arguments)) != len(arguments):
        add(issues, 'briefs.jsonl', 'error', 'The three briefs must have distinct titles and arguments')
    unique_claims, claim_ids_seen = {}, set()
    pubs_by_piece, referenced_items, referenced_assets = {}, {}, {}
    piece_urls = {pid: set() for pid in PIECES}
    for pid in PIECES:
        brief = brief_map.get(pid)
        if not brief:
            continue
        claims = brief.get('claims')
        if not isinstance(claims, list) or not claims:
            add(issues, 'briefs.jsonl', 'error', 'Brief has no claims', pid); continue
        piece_publishers, piece_items = set(), set()
        for claim in claims:
            cid = claim.get('claim_id')
            if not isinstance(cid, str) or not cid.startswith(pid + '-c') or cid in claim_ids_seen:
                add(issues, 'briefs.jsonl', 'error', 'Claim ID must use this piece prefix', pid)
            if isinstance(cid, str):
                claim_ids_seen.add(cid)
            if claim.get('type') not in ('reported_fact', 'source_claim', 'inference') or not isinstance(claim.get('statement'), str) or not claim['statement'].strip():
                add(issues, 'briefs.jsonl', 'error', f'Claim {cid} has an empty statement or invalid type', pid)
            evidence = claim.get('evidence')
            if not isinstance(evidence, list) or not evidence:
                add(issues, 'briefs.jsonl', 'error', f'Claim {cid} has no evidence', pid); continue
            for ref in evidence:
                if not isinstance(ref, dict):
                    add(issues, 'briefs.jsonl', 'error', f'Claim {cid} has malformed evidence reference', pid); continue
                item_id, version = ref.get('item_id'), ref.get('version_id')
                item = get_evidence(item_id, version) if item_id and version else None
                if item is None:
                    add(issues, 'briefs.jsonl', 'error', f'Claim {cid} references missing evidence {item_id}@{version}', pid); continue
                referenced_items[f'{item_id}@{version}'] = {k: item.get(k) for k in ('item_id', 'underlying_id', 'version_id', 'publisher_id', 'kind', 'title', 'published_at', 'url', 'media_url')}
                for asset_field in ('text_path', 'segments_path'):
                    asset_name = item.get(asset_field)
                    if asset_name:
                        try:
                            retained = repo_path(asset_name)
                            if not retained.is_file():
                                raise OSError('file is missing')
                            referenced_assets[str(retained)] = retained.read_bytes().hex()
                        except (BadInput, OSError) as exc:
                            add(issues, 'briefs.jsonl', 'error', f'Claim {cid}: referenced {asset_field} cannot be read: {exc}', pid)
                locator = ref.get('locator') or {}
                try:
                    expected_locator = 'text' if item.get('kind') == 'feed' else 'segment'
                    if locator.get('type') != expected_locator:
                        raise ValueError(f"{item.get('kind')} evidence requires a {expected_locator} locator")
                    if locator.get('type') == 'text':
                        text_path = repo_path(item['text_path'])
                        text = text_path.read_text(encoding='utf-8')
                        quote = locator.get('quote')
                        if not isinstance(quote, str) or not quote.strip() or quote not in text:
                            raise ValueError('quote is not an exact passage in the retained text')
                        referenced_assets[str(text_path)] = text_path.read_bytes().hex()
                    elif locator.get('type') == 'segment':
                        segment_path = repo_path(item['segments_path'])
                        segments = load_json(segment_path)
                        seg = next((s for s in segments if s.get('segment_id') == locator.get('segment_id')), None)
                        if not seg or not isinstance(seg.get('text'), str) or not seg['text'].strip():
                            raise ValueError('segment locator does not resolve to a substantive segment')
                        start, end = seg.get('start_seconds'), seg.get('end_seconds')
                        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end < start:
                            raise ValueError('segment has invalid timestamps')
                        referenced_assets[str(segment_path)] = segment_path.read_bytes().hex()
                    else:
                        raise ValueError('locator must identify exact text or a real transcript segment')
                except (BadInput, OSError, KeyError, ValueError, TypeError) as exc:
                    add(issues, 'briefs.jsonl', 'error', f'Claim {cid}: {exc}', pid)
                    continue
                if item.get('kind') not in ('feed', 'youtube', 'podcast') or not item.get('publisher_id'):
                    add(issues, 'briefs.jsonl', 'error', f'Evidence {item_id} lacks a supported kind or independent publisher ID', pid)
                try:
                    pubdate = parse_utc_date(item['published_at'])
                    if not (as_day - dt.timedelta(days=29) <= pubdate <= as_day):
                        add(issues, 'briefs.jsonl', 'error', f'Evidence {item_id} falls outside the inclusive 30-day window', pid)
                except (KeyError, TypeError, ValueError):
                    add(issues, 'briefs.jsonl', 'error', f'Evidence {item_id} has invalid or unknown publication date', pid)
                if item.get('publisher_id'):
                    piece_publishers.add(item['publisher_id'])
                piece_items.add(underlying_id(item))
                if item.get('url'):
                    piece_urls[pid].add(item['url'])
                unique_claims.setdefault(cid, claim)
                referenced_items.setdefault('@' + str(item_id), dict(item, _underlying=underlying_id(item)))
        pubs_by_piece[pid] = piece_publishers
        if len(piece_publishers) < 3:
            add(issues, 'briefs.jsonl', 'error', f'Piece cites {len(piece_publishers)} independent publishers; at least 3 are required', pid)
        if not brief.get('title') or not brief.get('argument') or not brief.get('synthesis') or not brief.get('limitations'):
            add(issues, 'briefs.jsonl', 'error', 'Brief is missing title, argument, synthesis, or limitations', pid)
    eligible = read_records(run / 'eligible.jsonl') if (run / 'eligible.jsonl').is_file() else []
    if (run / 'eligible.jsonl').is_file():
        inputs['eligible.jsonl'] = (run / 'eligible.jsonl').read_bytes().hex()
    eligible_unique = {underlying_id(x): x for x in eligible if underlying_id(x)}
    if len(eligible_unique) < 12:
        add(issues, 'eligible.jsonl', 'error', f'Eligible corpus has {len(eligible_unique)} distinct underlying items; at least 12 are required')
    eligible_publishers = {x.get('publisher_id') for x in eligible_unique.values() if x.get('publisher_id')}
    if len(eligible_publishers) < 6:
        add(issues, 'eligible.jsonl', 'error', f'Eligible corpus has {len(eligible_publishers)} independent publishers; at least 6 are required')
    for kind in ('feed', 'youtube', 'podcast'):
        eligible_kind = {underlying_id(x) for x in eligible_unique.values() if x.get('kind') == kind}
        if len(eligible_kind) < 2:
            add(issues, 'eligible.jsonl', 'error', f'Eligible corpus has {len(eligible_kind)} distinct {kind} item(s); at least 2 are required')
        if not any(x.get('kind') == kind for x in referenced_items.values()):
            add(issues, 'briefs.jsonl', 'error', f'The series does not cite any {kind} evidence')
    # Resolve each manifest path, check claim markers and article/script consistency.
    texts = {'articles': {}, 'video_scripts': {}}
    for kind, recs in manifests.items():
        for m in recs or []:
            pid = str(m.get('piece_id'))
            try:
                path = repo_path(m['path'])
                text = path.read_text(encoding='utf-8')
                inputs[str(path)] = path.read_bytes().hex()
                texts[kind][pid] = text
                if as_of not in text:
                    add(issues, f'{kind}/{pid}', 'error', 'Draft must state this run’s as-of date', pid)
                if not any(url in text for url in piece_urls.get(pid, set())):
                    add(issues, f'{kind}/{pid}', 'error', 'Draft must include an external source URL, not only internal claim markers', pid)
                declared = set(m.get('claim_ids', []))
                actual = {c.get('claim_id') for c in brief_map.get(pid, {}).get('claims', [])}
                if not declared or declared != actual:
                    add(issues, f'{kind}/{pid}', 'error', 'Manifest claim_ids must exactly match this piece’s brief claims', pid)
                for cid in declared:
                    if cid not in text:
                        add(issues, f'{kind}/{pid}', 'error', f'Draft is missing claim marker {cid}', pid)
            except (BadInput, OSError, KeyError, TypeError) as exc:
                add(issues, f'{kind}/{pid}', 'error', f'Draft path cannot be read: {exc}', pid)
    for pid in PIECES:
        article, script = texts['articles'].get(pid), texts['video_scripts'].get(pid)
        if article is not None:
            n = count_words(article_body(article))
            if not 600 <= n <= 900:
                add(issues, f'articles/{pid}', 'warning', f'Article is approximately {n} words; target is 600–900', pid)
        if script is not None:
            narration = narration_text(script)
            if narration is None:
                add(issues, f'video_scripts/{pid}', 'warning', 'Could not isolate labeled Narration blocks; spoken word count was not assessed', pid)
            else:
                n = spoken_word_count(narration)
                if not 390 <= n <= 750:
                    add(issues, f'video_scripts/{pid}', 'warning', f'Narration is approximately {n} spoken words; target is 390–750', pid)
        if article is not None and script is not None:
            ac = set(cid for cid in unique_claims if cid.startswith(pid + '-'))
            if not ac <= set(cid for cid in ac if cid in article and cid in script):
                add(issues, f'piece/{pid}', 'error', 'Article and video script do not share all brief claim markers', pid)
    add(issues, 'human review', 'warning', 'A person must assess factual accuracy, synthesis, attribution, uncertainty, and audience suitability.')
    fingerprint_payload = {'as_of_date': as_of, 'inputs': inputs, 'referenced_items': referenced_items, 'referenced_assets': referenced_assets}
    review_id = digest(fingerprint_payload)
    review = {'review_id': review_id, 'passed': not any(i['severity'] == 'error' for i in issues), 'issues': issues}
    if write:
        write_json(run / 'review.json', review)
    if emit:
        print(json.dumps(review, ensure_ascii=False))
    receipt.input_count = sum(len(v or []) for v in records.values())
    receipt.output_count = 1
    return review if not write else 0

if __name__ == '__main__':
    raise SystemExit(stage_main('review/check_content', assess))
