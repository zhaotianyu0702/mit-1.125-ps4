#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from common import BadInput, emit, load_json, read_jsonl, read_records, stage_main
from model import infer_validated
from evidence import context, validate_briefs

def briefs(run, receipt):
    decisions = read_jsonl(sys.stdin)
    receipt.input_count = len(decisions)
    eligible = read_records(run / 'eligible.jsonl')
    selected = {(d['item_id'], d['version_id']) for d in decisions if d.get('decision') == 'accept'}
    items = [i for i in eligible if (i['item_id'], i['version_id']) in selected]
    publishers = {i['publisher_id'] for i in items}
    if len(items) < 3 or len(publishers) < 3:
        raise RuntimeError('Insufficient accepted evidence: three independent publishers needed before drafting')
    for pid in ('01', '02', '03'):
        keys = {(d['item_id'], d['version_id']) for d in decisions if d.get('decision') == 'accept' and pid in d['piece_ids']}
        if len({i['publisher_id'] for i in items if (i['item_id'], i['version_id']) in keys}) < 3:
            raise RuntimeError(f'Insufficient independent accepted evidence assigned to piece {pid}')
    instructions = (run / 'prompts/create_briefs.md').read_text() + '\nEDITORIAL POLICY:\n' + (run / 'config/editorial_policy.md').read_text()
    rows=[]
    angles={'01':'What changed in coding-agent delivery and why it matters',
            '02':'What recent source claims actually measure, and which conclusions remain unverified',
            '03':'What a small team should measure in a reversible adoption trial'}
    for pid in ('01','02','03'):
        assigned=[d for d in decisions if d.get('decision')=='accept' and pid in d['piece_ids']]
        keys={(d['item_id'],d['version_id']) for d in assigned}
        supplied=[i for i in items if (i['item_id'],i['version_id']) in keys]
        shape={'brief': {'piece_id':pid, 'title':'title', 'question':'question', 'argument':'distinct argument',
                'synthesis':'cross-source reasoning', 'limitations':'meaningful limitation or counterargument',
                'claims':[{'claim_id':pid+'-c1', 'statement':'claim', 'type':'reported_fact|source_claim|inference',
                           'evidence':[{'item_id':'exact input ID', 'version_id':'exact input version',
                                        'locator':{'type':'text','quote':'a short exact contiguous quote for a feed; for media use type segment and segment_id instead'}}]}]},
               'error':None}
        task_instructions=instructions+'\nThis invocation produces ONLY piece '+pid+' of the series; the shell stage will combine three separate invocations. Write the brief in English. Focus: '+angles[pid]+'. Return one brief with at least three independent publishers and 4–6 well-supported claims. A critical audit may conclude that productivity is unverified: it does not need to establish a positive productivity result. Attribute vendor results as source_claim, describe their actual task and limits, and distinguish observations from proposed tests. Do not assert missing controls or independent validation are absent from a full source when only excerpts were supplied. At least one claim should connect multiple sources explicitly. Use exact locator objects: {"type":"text","quote":"..."} for written evidence or {"type":"segment","segment_id":"s-..."} for media. If even a qualified critical audit cannot be supported, return brief:null and error explaining the specific missing evidence. Do not invent evidence or silently return an empty list.'
        required_kinds=set()
        if pid=='03':
            by_key={(i['item_id'],i['version_id']):i for i in items}
            used={by_key[(e['item_id'],e['version_id'])]['kind'] for b in rows for c in b['claims'] for e in c['evidence']}
            required_kinds={'feed','youtube','podcast'}-used
            if required_kinds:
                if not required_kinds <= {i['kind'] for i in supplied}:
                    raise BadInput('Accepted piece-03 evidence cannot supply the remaining required source kinds: '+', '.join(sorted(required_kinds)))
                task_instructions+='\nSERIES COVERAGE: Prior briefs do not yet cite '+', '.join(sorted(required_kinds))+'. This final brief must make substantive use of accepted evidence of those kinds where the supplied passages support a relevant claim. Use a qualified implementation observation or proposed measurement when warranted; do not invent findings or inflate credibility to satisfy coverage. If no such contribution is supportable, report the specific evidence gap.'
        def validate_response(response):
            brief=response.get('brief')
            if not isinstance(brief,dict) or brief.get('piece_id')!=pid:
                raise BadInput('Model could not produce brief '+pid+': '+str(response.get('error') or 'missing requested brief'))
            checked=validate_briefs([brief], supplied, (pid,))[0]
            by_key={(i['item_id'],i['version_id']):i for i in supplied}
            used={by_key[(e['item_id'],e['version_id'])]['kind'] for c in checked['claims'] for e in c['evidence']}
            if not required_kinds <= used:
                raise BadInput('Final brief omits required substantive evidence kinds: '+', '.join(sorted(required_kinds-used)))
            return checked
        brief=infer_validated(run,receipt,'create_briefs',task_instructions,
                       {'piece_id':pid,'series_angles':angles,'project':load_json(run/'config/project.json'),
                        'as_of_date':load_json(run/'run.json')['as_of_date'],'decisions':assigned,
                        'prior_brief_arguments':[{'piece_id':r['piece_id'],'argument':r['argument']} for r in rows],
                        'items':[context(i,6000) for i in supplied]},shape,validate_response)
        rows.append(brief)
    rows = validate_briefs(rows, items)
    receipt.output_count = 3
    emit(rows)

if __name__ == '__main__':
    raise SystemExit(stage_main('editorial/create_briefs', briefs))
