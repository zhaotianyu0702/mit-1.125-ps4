#!/usr/bin/env python3
import datetime as dt
import copy
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from common import BadInput, atomic_write, emit, load_json, read_jsonl, repo_path, stage_main, write_json
from model import infer_validated
from evidence import context

def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def confirmed_sample_overrides(run, items):
    """Return exact-version confirmed sample choices, with immutable run-local provenance."""
    project=load_json(run/'config/project.json')
    ref=project.get('student_feedback_record')
    if not isinstance(ref,str) or not ref:
        return {}, None
    feedback_path=repo_path(ref)
    if not feedback_path.is_file():
        raise BadInput('Configured student feedback record is missing')
    feedback=load_json(feedback_path)
    scope=feedback.get('scope')
    if not isinstance(scope,dict) or scope.get('six_sample_decisions_confirmed') is not True:
        return {}, None
    source_id=feedback.get('source_message_id')
    if not isinstance(source_id,str) or not source_id:
        raise BadInput('Confirmed student feedback lacks its source message identifier')
    sample_path=feedback_path.parent/'student_review_sample.jsonl'
    decisions_path=feedback_path.parent/'decisions.jsonl'
    if not sample_path.is_file() or not decisions_path.is_file():
        raise BadInput('Confirmed feedback sample or prior decisions file is missing')
    with sample_path.open(encoding='utf-8') as f: samples=read_jsonl(f)
    with decisions_path.open(encoding='utf-8') as f: prior=read_jsonl(f)
    eligible={(x.get('item_id'),x.get('version_id')) for x in items}
    sample_map={}
    for row in samples:
        key=(row.get('item_id'),row.get('version_id'))
        if (not all(isinstance(x,str) and x for x in key) or key in sample_map
                or row.get('source_message_id')!=source_id
                or row.get('student_decision') not in ('accept','reject','defer')):
            raise BadInput('Confirmed student review sample has malformed or duplicate decisions')
        sample_map[key]=row
    prior_map={}
    for row in prior:
        key=(row.get('item_id'),row.get('version_id'))
        if key in prior_map: raise BadInput('Prior decision file has duplicate item/version rows')
        prior_map[key]=row
    exact={k:v for k,v in sample_map.items() if k in eligible}
    matched_prior={}
    for key,row in exact.items():
        old=prior_map.get(key)
        if not old or old.get('decision') not in ('accept','reject','defer'):
            raise BadInput('Confirmed sample choice lacks its exact-version prior editorial decision')
        if row['student_decision']=='accept' and not (
                isinstance(old.get('piece_ids'),list) and old['piece_ids']):
            raise BadInput('Accepted sample choice lacks prior intended piece assignments')
        matched_prior[key]=old
    snapshot=run/'student_feedback_carry_forward'
    snapshot.mkdir(parents=True,exist_ok=True)
    data_files={
        'feedback.json':feedback_path.read_bytes(),
        'student_review_sample.jsonl':sample_path.read_bytes(),
        'prior_decisions.jsonl':(''.join(json.dumps(matched_prior[k],ensure_ascii=False,sort_keys=True)+'\n'
            for k in sorted(matched_prior)).encode('utf-8')),
    }
    hashes={}
    for name,content in data_files.items():
        dest=snapshot/name
        if dest.exists() and dest.read_bytes()!=content:
            raise BadInput('Existing student feedback provenance snapshot does not match configured source')
        if not dest.exists(): dest.write_bytes(content)
        hashes[name]=hashlib.sha256(content).hexdigest()
    manifest={'provenance_type':'historical_confirmed_sample_decisions',
        'source_message_id':source_id,'feedback_record_path':str(feedback_path.relative_to(repo_path('.'))),
        'source_reviewed_at_utc':feedback.get('user_message_at_utc'),
        'accepted_policy_sha256':feedback.get('accepted_policy_sha256'),
        'snapshots':hashes,'matched_exact_item_versions':[
            {'item_id':k[0],'version_id':k[1],'student_decision':v['student_decision'],
             'prior_ai_decision':matched_prior[k].get('decision')} for k,v in sorted(exact.items())],
        'student_personal_source_inspection_claimed':bool(scope.get('student_personal_source_inspection_claimed',False)),
        'student_audio_verified':bool(scope.get('source_audio_verified_by_student',False)),
        'full_draft_approval':bool(scope.get('full_drafts_approved',False)),
        'publication_authorized':False}
    manifest_path=snapshot/'manifest.json'
    if manifest_path.exists() and load_json(manifest_path)!=manifest:
        raise BadInput('Existing feedback carry-forward manifest differs from current inputs')
    if not manifest_path.exists(): write_json(manifest_path,manifest)
    overrides={}
    for key,row in exact.items():
        old=matched_prior[key]
        overrides[key]={'decision':row['student_decision'],
            'reason':old.get('reason','Confirmed sample decision carried forward from exact-version prior editorial review.'),
            'piece_ids':old.get('piece_ids',[]) if row['student_decision']=='accept' else [],
            'student_decision_provenance':{'type':'historical_confirmed_sample_decision',
                'source_message_id':source_id,'reviewed_at_utc':row.get('reviewed_at'),
                'snapshot_manifest':'student_feedback_carry_forward/manifest.json',
                'snapshot_sha256':hashes['student_review_sample.jsonl'],
                'prior_editorial_snapshot_sha256':hashes['prior_decisions.jsonl'],
                'prior_ai_decision':old.get('decision')}}
    return overrides,manifest

def select(run, receipt):
    items = read_jsonl(sys.stdin)
    receipt.input_count = len(items)
    if not items:
        raise RuntimeError('No eligible evidence available for editorial selection')
    settings = load_json(run / 'config/ai.json')
    size = settings.get('selection_batch_size', 5)
    if not isinstance(size, int) or not 1 <= size <= 20:
        raise BadInput('selection_batch_size must be between 1 and 20')
    metadata = load_json(run / 'run.json')
    try:
        as_of = dt.date.fromisoformat(metadata['as_of_date'])
    except (KeyError, TypeError, ValueError) as exc:
        raise BadInput('run.json must contain an ISO as_of_date') from exc
    window_start = as_of - dt.timedelta(days=29)
    window = {'start_date': window_start.isoformat(), 'end_date': as_of.isoformat(),
              'timezone': 'UTC', 'inclusive': True}
    instructions = (run / 'prompts/select_items.md').read_text() + '\n' + (
        'AUTHORITATIVE FRESHNESS WINDOW FOR THIS RUN (UTC calendar dates, inclusive): '
        f"{window['start_date']} through {window['end_date']}. Use this exact window; "
        'do not infer dates from student feedback, project configuration, the system clock, '
        'or source text. Apply the saved eligibility and editorial policy to any item whose '
        'date falls outside or cannot be established.\n'
        '\nEDITORIAL POLICY:\n' + (run / 'config/editorial_policy.md').read_text())
    shape = {'decisions': [{'item_id': 'exact input ID', 'version_id': 'exact input version', 'decision': 'accept|reject|defer', 'reason': 'claim-specific reasons and uncertainty', 'piece_ids': ['01', '02', '03']}]}
    results = []
    raw_model_decisions = []
    overrides,feedback_manifest=confirmed_sample_overrides(run,items)
    for start in range(0, len(items), size):
        batch = items[start:start + size]
        expected = {(i['item_id'], i['version_id']) for i in batch}
        def validate(answer):
            rows=answer.get('decisions')
            if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):
                raise BadInput('Model decisions must be a list of objects')
            actual={(r.get('item_id'),r.get('version_id')) for r in rows}
            if len(rows)!=len(expected) or actual!=expected:
                raise BadInput('Model must provide exactly one decision per input version; missing='+repr(sorted(expected-actual))+'; unexpected='+repr(sorted(actual-expected)))
            for row in rows:
                if row.get('decision') not in ('accept','reject','defer') or not isinstance(row.get('reason'),str) or not row['reason'].strip():
                    raise BadInput('Invalid model decision/reason')
                pids=row.get('piece_ids')
                if not isinstance(pids,list) or any(p not in ('01','02','03') for p in pids) or len(pids)!=len(set(pids)):
                    raise BadInput('Invalid decision piece_ids')
                if (row['decision']=='accept')!=bool(pids):
                    raise BadInput('Accepted items need intended pieces; rejected/deferred items cannot have pieces')
            return rows
        rows=infer_validated(run,receipt,'select_items',instructions,{
            'project':load_json(run/'config/project.json'),
            'as_of_date': as_of.isoformat(),
            'freshness_window': window,
            'items':[context(i) for i in batch]},shape,validate)
        raw_model_decisions.extend(copy.deepcopy(rows))
        for row in rows:
            key=(row['item_id'],row['version_id'])
            carried=overrides.get(key)
            if carried:
                model_decision={k:row[k] for k in ('decision','reason','piece_ids')}
                row.update(carried)
                row['selection_provenance']={
                    'selected_by':'exact_version_student_confirmed_sample',
                    'historical_feedback_manifest':'student_feedback_carry_forward/manifest.json',
                    'new_model_decision':model_decision,
                    'model_disagreed_with_student':model_decision['decision']!=row['decision'],
                    'student_audio_verified':False,'full_draft_approval':False}
            results.append(row)
    receipt.output_count = len(results)
    atomic_write(run/'selection_ai_decisions.jsonl', ''.join(
        json.dumps(row,ensure_ascii=False)+'\n' for row in raw_model_decisions))
    emit(results)

if __name__ == '__main__':
    raise SystemExit(stage_main('editorial/select_items', select))
