"""Entry-point metadata/snapshots and orchestration receipts, not stage logic."""
import datetime as dt
import hashlib
import importlib.metadata
import json
import shutil
import sys
import uuid
from common import ROOT, BadInput, Receipt, load_json, repo_path, utcnow, write_json

def initialize():
    project = load_json(ROOT / 'config/project.json')
    for key in ('publication_name', 'topic', 'audience', 'central_question'):
        if not isinstance(project.get(key), str) or not project[key].strip():
            raise BadInput(f'project.json needs {key}')
    sources = load_json(ROOT / 'config/sources.json')
    if not isinstance(sources, list) or not sources:
        raise BadInput('sources.json must be a nonempty array')
    ids = set()
    for source in sources:
        if not isinstance(source, dict):
            raise BadInput('Every source must be an object')
        for key in ('source_id', 'publisher_id', 'kind', 'url'):
            if not isinstance(source.get(key), str) or not source[key]:
                raise BadInput(f'Source needs {key}')
        if source['source_id'] in ids:
            raise BadInput('source_id values must be unique')
        ids.add(source['source_id'])
        if source['kind'] not in ('feed', 'youtube', 'podcast') or not source['url'].startswith(('http://', 'https://')):
            raise BadInput('Source kind or HTTP URL invalid')
    if {s['kind'] for s in sources} != {'feed', 'youtube', 'podcast'}:
        raise BadInput('Configure all three input types')
    for filename in ('select_items', 'create_briefs', 'write_articles', 'write_video_scripts'):
        if not (ROOT / 'prompts' / (filename + '.md')).read_text().strip():
            raise BadInput(f'Prompt {filename} is empty')
    if not (ROOT / 'config/editorial_policy.md').read_text().strip():
        raise BadInput('Editorial policy is empty')
    now = dt.datetime.now(dt.timezone.utc)
    rid = now.strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    run = ROOT / 'runs' / rid
    previous = []
    for p in (ROOT / 'runs').glob('*/run.json'):
        try:
            record = load_json(p)
            if record.get('mode') == 'live':
                previous.append(record)
        except BadInput:
            pass
    prior = max(previous, key=lambda x: x['started_at'])['run_id'] if previous else None
    run.mkdir(parents=True)
    for folder in ('config', 'prompts'):
        shutil.copytree(ROOT / folder, run / folder)
    write_json(run / 'run.json', {'run_id': rid, 'started_at': utcnow(), 'as_of_date': now.date().isoformat(),
               'mode': 'live', 'previous_run_id': prior})
    implementation = [ROOT / 'run.sh', ROOT / 'requirements-lock.txt']
    for component in ('lib', 'workflows', 'collectors', 'processing', 'data', 'editorial', 'content', 'review', 'publishing', 'reporting', 'adapters'):
        implementation.extend(p for p in (ROOT / component).glob('*') if p.suffix in ('.py', '.sh'))
    dependencies = {}
    for package in ('yt-dlp', 'trafilatura', 'imageio-ffmpeg'):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = None
    write_json(run / 'implementation.json', {
        'recorded_at': utcnow(), 'note': 'Implementation hashes captured before stage execution.',
        'python': sys.version.split()[0], 'dependencies': dependencies,
        'files': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(implementation) if p.is_file()}})
    rec = Receipt(run, 'run:init')
    rec.input_count = len(sources)
    rec.output_count = 1
    rec.save()
    print(run.relative_to(ROOT))

def workflow_receipt():
    run, name, start, code = sys.argv[2:6]
    rec = Receipt(repo_path(run), name, ['bash'])
    rec.started_at = start
    for error in sys.argv[6:]:
        rec.errors.append(error)
    rec.save(int(code))

def resume_run():
    if len(sys.argv) != 3:
        raise BadInput('Usage: runtime.py resume RUN_DIR')
    run = repo_path(sys.argv[2])
    meta_path = run / 'run.json'
    if not meta_path.is_file():
        raise BadInput('RUN_DIR must contain run.json')
    meta = load_json(meta_path)
    if meta.get('mode') != 'live':
        raise BadInput('Only a genuine live run can be resumed; start a new live run')
    try:
        as_of = dt.date.fromisoformat(meta.get('as_of_date'))
    except (TypeError, ValueError) as exc:
        raise BadInput('run.json has an invalid as_of_date; start a new live run') from exc
    today = dt.datetime.now(dt.timezone.utc).date()
    if as_of != today:
        raise BadInput(f'Cannot resume a run from {as_of.isoformat()} on {today.isoformat()} UTC; start a new live run')
    if not (run / 'eligible.jsonl').is_file():
        raise BadInput('Cannot resume without saved eligible.jsonl; start a new live run')
    if not (run / 'config').is_dir() or not (run / 'prompts').is_dir():
        raise BadInput('Cannot resume without the run config and prompt snapshots')

    resumed_at = utcnow()
    attempt_id = resumed_at.replace(':', '').replace('-', '') + '-' + uuid.uuid4().hex[:6]
    attempt = run / 'attempts' / ('resume-' + attempt_id)
    previous = attempt / 'pre_resume'
    previous.mkdir(parents=True)
    preserve = ('run.json', 'config', 'prompts', 'logs', 'model_calls', 'decisions.jsonl',
                'decisions.jsonl.partial', 'briefs.jsonl', 'briefs.jsonl.partial', 'articles.jsonl',
                'articles.jsonl.partial', 'articles', 'video_scripts.jsonl', 'video_scripts.jsonl.partial',
                'video_scripts', 'review.json', '.review.tmp', 'summary.json', 'approval.json')
    preserve = preserve + ('student_feedback_carry_forward', 'selection_ai_decisions.jsonl')
    archived = []
    for name in preserve:
        src = run / name
        if not src.exists():
            continue
        dst = previous / name
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        archived.append(name)
    # A prior human decision is retained in the attempt archive, but never reused for resumed drafts.
    old_approval = run / 'approval.json'
    if old_approval.exists():
        old_approval.unlink()
    hash_paths = [run / 'eligible.jsonl', run / 'items.jsonl', run / 'changes.jsonl', run / 'exclusions.jsonl']
    hash_paths.extend(p for folder in ('config', 'prompts') for p in sorted((run / folder).rglob('*')) if p.is_file())
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in hash_paths if p.is_file()}
    implementation = [ROOT / 'run.sh', ROOT / 'requirements-lock.txt']
    for folder in ('lib', 'workflows', 'collectors', 'processing', 'data', 'editorial',
                   'content', 'review', 'publishing', 'reporting', 'adapters'):
        implementation.extend(p for p in (ROOT / folder).glob('*') if p.suffix in ('.py', '.sh'))
    implementation_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(implementation) if p.is_file()}
    write_json(attempt / 'resume.json', {
        'run_id': meta['run_id'], 'mode': meta['mode'], 'as_of_date': meta['as_of_date'],
        'resumed_at': resumed_at, 'operation': 'rerun create_series only; collection and extraction are not repeated',
        'preserved_before_resume': archived, 'input_sha256': hashes,
        'implementation_sha256': implementation_hashes,
        'approval_action': 'previous approval, if present, archived and removed; new student review required'})
    rec = Receipt(run, 'run:resume_snapshot', ['python3'])
    rec.started_at = resumed_at
    rec.input_count = len(hashes)
    rec.output_count = len(archived) + 1
    rec.save(0)
    print(run.relative_to(ROOT))

if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['init']:
            initialize()
        elif sys.argv[1:2] == ['receipt'] and len(sys.argv) >= 6:
            workflow_receipt()
        elif sys.argv[1:2] == ['resume']:
            resume_run()
        else:
            raise BadInput('Usage: runtime.py init | resume RUN_DIR | receipt RUN_DIR STAGE START CODE [ERROR...]')
    except (BadInput, OSError, KeyError, TypeError, ValueError) as exc:
        print(f'run: {exc}', file=sys.stderr)
        sys.exit(2)
