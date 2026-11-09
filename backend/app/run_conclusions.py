from collections import Counter
import hashlib
import json
import re
from typing import Literal
from uuid import uuid4
import asyncio

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.access import actor_context
from app.ai import MODEL, ROUTING, STRUCTURE
from app.projects import utc_now


STATES = ('unreviewed', 'needs_fix', 'intentional', 'insufficient_data')
KINDS = ('intersection', 'clearance', 'surface_review')
INPUT_TOKENS, OUTPUT_TOKENS = 2048, 512


class Priority(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    group_id: str = Field(pattern=r'^g[1-6]$')
    action: Literal['verify_geometry', 'review_routing', 'review_clearance', 'coordinate_structure']
    rationale: str = Field(min_length=10, max_length=350)


class ConclusionProposal(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    assessment: Literal['incomplete', 'findings', 'clear_in_scope']
    summary: str = Field(min_length=10, max_length=700)
    priorities: list[Priority] = Field(max_length=3)
    next_steps: list[Literal['verify_geometry', 'review_design_intent', 'review_system_requirements', 'structural_approval', 'recheck_geometry']] = Field(min_length=1, max_length=5)
    citations: list[str] = Field(min_length=1, max_length=7)
    requires_review: Literal[True]


def build_evidence(report, reviews):
    coverage = report.get('coverage') or {}
    if report.get('status') not in {'completed', 'partial'} or not coverage.get('tested_elements'):
        raise HTTPException(409, 'ai_summary_no_evidence')
    issues = report['issues']
    by_review = {item['issue_id']: item['review'] for item in reviews}
    sources = {item['id']: item for item in report.get('sources', [])}
    counts = Counter({kind: 0 for kind in KINDS})
    review_counts = Counter({state: 0 for state in STATES})
    groups, revisions = {}, []
    for issue in issues:
        kind = issue['kind']
        if kind not in KINDS:
            raise HTTPException(409, 'ai_summary_no_evidence')
        counts[kind] += 1
        review = by_review.get(issue['id'], {})
        state = review.get('state', 'unreviewed')
        state = state if state in STATES else 'unreviewed'
        review_counts[state] += 1
        revisions.append((issue['id'], state, review.get('revision', 0)))
        sides = sorted((side['source_id'], side['ifc_type'], side.get('storey_guid') or '') for side in (issue['a'], issue['b']))
        key = (kind, *sides)
        if key not in groups:
            groups[key] = {'kind':kind, 'count':0, 'types':[side[1] for side in sides],
                           'disciplines':[sources.get(side[0], {}).get('discipline', 'OTHER') for side in sides],
                           'source_names':[sources.get(side[0], {}).get('name', side[0]) for side in sides],
                           'review_counts':{state:0 for state in STATES}, 'representative':issue}
        group = groups[key]
        group['count'] += 1
        group['review_counts'][state] += 1
        if issue['id'] < group['representative']['id']:
            group['representative'] = issue
    ranked = sorted(groups.values(), key=lambda group: (-(group['count'] - group['review_counts']['intentional']), -group['count'], group['representative']['id']))
    selected = []
    for kind in KINDS:
        first = next((group for group in ranked if group['kind'] == kind), None)
        if first is not None:
            selected.append(first)
    selected += [group for group in ranked if group not in selected][:6 - len(selected)]
    selected.sort(key=lambda group: ranked.index(group))
    sampled = []
    for index, group in enumerate(selected, 1):
        original = group['representative']
        pair = {key:original[key] for key in ('id', 'a', 'b', 'point_m') if key in original}
        for side in ('a', 'b'):
            pair[side] = {**pair[side], 'name':(pair[side].get('name') or '')[:180]}
        sampled.append({**group, 'id':f'g{index}', 'representative':pair})
    evidence = {'scope':'all_saved_issues', 'run_id':report['id'], 'run_status':report['status'],
                'assessment':'incomplete' if report['status']=='partial' or report.get('verdict') in {'incomplete','unavailable'} else 'findings' if issues else 'clear_in_scope',
                'issue_count':len(issues), 'kind_counts':dict(counts), 'review_counts':dict(review_counts),
                'coverage':coverage, 'parameters':report.get('parameters', {}),
                'diagnostics':list(dict.fromkeys(item['code'] for item in report.get('diagnostics', []))),
                'sources':report.get('sources', []), 'group_count':len(groups), 'groups':sampled}
    fingerprint = {**evidence, 'review_revisions':sorted(revisions)}
    evidence['signature'] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return evidence


def prompt_messages(evidence):
    system = (
        'Summarize BIM coordination evidence in Vietnamese. ONLY one compact JSON object. '
        'The app displays exact numbers separately: NEVER put digits, measurements, GUIDs, URLs or codes in summary/rationale. '
        'Never claim safety, design approval, a completed fix, or move structural elements. '
        'Schema: {"assessment":the provided assessment,"summary":short Vietnamese recommendation,'
        '"priorities":[{"group_id":provided group ID,"action":enum,"rationale":short Vietnamese text}],'
        '"next_steps":[enum],"citations":["stats",used group IDs],"requires_review":true}. '
        'Use at most TWO priorities and TWO next_steps; summary/rationale each under thirty Vietnamese words. '
        'Actions: verify_geometry; review_routing only for MEP/routing groups; review_clearance only for clearance; '
        'coordinate_structure only for structural groups. Surface_review allows ONLY verify_geometry. '
        'Next_steps: verify_geometry,review_design_intent,review_system_requirements,structural_approval,recheck_geometry. '
        'Always cite stats and every selected group ID. For no findings use empty priorities. '
        'Groups are representative, not every individual issue. '
        'Pending HUMAN review is not missing or untested geometry. Only missing_geometry indicates missing geometry. '
        'Use recommendations, not claims that design defects are confirmed.'
    )
    def volume(number):
        if number == 0: return 'none'
        if number < 10: return 'few'
        if number < 100: return 'dozens'
        if number < 1000: return 'hundreds'
        return 'thousands'
    def human_status(counts):
        return {'pending_human_review':bool(counts['unreviewed']), 'has_needs_fix_labels':bool(counts['needs_fix']),
                'has_intentional_labels':bool(counts['intentional']), 'has_insufficient_data_labels':bool(counts['insufficient_data'])}
    # Keep exact counts in the saved evidence/UI; the small model must not turn them into invented measurements.
    facts = {'scope':evidence['scope'],'assessment':evidence['assessment'],'finding_volume':volume(evidence['issue_count']),
             'finding_types':{kind:volume(count) for kind,count in evidence['kind_counts'].items()},
             'geometry':{'missing_geometry':bool(evidence['coverage'].get('missing_geometry')), 'open_meshes':bool(evidence['coverage'].get('nonmanifold'))},
             'human_annotations':human_status(evidence['review_counts']), 'group_scope':'representative_groups_only'}
    facts['groups'] = [{**{key:group[key] for key in ('id','kind','types','disciplines')},
                       'finding_volume':volume(group['count']), 'human_annotations':human_status(group['review_counts'])} for group in evidence['groups']]
    return [{'role':'system','content':system}, {'role':'user','content':json.dumps(facts,ensure_ascii=False,separators=(',',':'))}]


def validate_conclusion(text, evidence):
    try:
        stripped = text.strip()
        if stripped.startswith('```json') and stripped.endswith('```'):
            stripped = stripped[7:-3].strip()
        proposal = ConclusionProposal.model_validate_json(stripped).model_dump()
        groups = {group['id']:group for group in evidence['groups']}
        citations = set(proposal['citations'])
        if proposal['assessment'] != evidence['assessment'] or 'stats' not in citations or not citations <= {'stats', *groups}:
            raise ValueError
        if groups and not proposal['priorities']:
            raise ValueError
        texts = [proposal['summary'], *(item['rationale'] for item in proposal['priorities'])]
        references = r'\b(?:' + '|'.join(re.escape(key) for key in groups if key in citations) + r')\b' if groups else r'(?!)'
        if any(re.search(r'\d|https?://|`|\b[A-Za-z0-9_$]{20,}\b', re.sub(references,'',re.sub(r'\b3D\b','',value,flags=re.I))) for value in texts):
            raise ValueError
        used = set()
        for item in proposal['priorities']:
            identifier, action = item['group_id'], item['action']
            if identifier not in groups or identifier not in citations or identifier in used:
                raise ValueError
            used.add(identifier)
            group = groups[identifier]
            if group['kind']=='surface_review' and action!='verify_geometry':
                raise ValueError
            if action=='review_routing' and 'MEP' not in group['disciplines'] and not ROUTING.intersection(group['types']):
                raise ValueError
            if action=='review_clearance' and group['kind']!='clearance':
                raise ValueError
            if action=='coordinate_structure' and 'STR' not in group['disciplines'] and not STRUCTURE.intersection(group['types']):
                raise ValueError
        mandatory = ['review_design_intent','recheck_geometry']
        if evidence['assessment']=='incomplete':
            mandatory.insert(0,'verify_geometry')
        proposal['next_steps'] = list(dict.fromkeys([*proposal['next_steps'],*mandatory]))
        return proposal
    except (AttributeError,ValueError,KeyError,TypeError,ValidationError):
        raise HTTPException(422,'ai_output_invalid') from None


class RunConclusions:
    def __init__(self, ai):
        self.ai, self.projects = ai, ai.projects
        self.collection = self.projects.database.project_conclusions

    def evidence(self, project_id, run_id):
        self.projects.require_run(project_id, run_id)
        report = self.projects.read_report(run_id, 'clashes')
        if report.get('project_id') != str(project_id):
            raise HTTPException(404,'run_not_found')
        return build_evidence(report, self.projects.reviews(project_id, run_id)['issues'])

    def history(self, project_id, run_id, offset, limit):
        current = self.evidence(project_id, run_id)
        query = {'project_id':str(project_id),'run_id':run_id}
        rows = self.collection.find(query).sort([('created_at',-1),('_id',1)]).skip(offset).limit(limit)
        return {'items':[{'id':row.pop('_id'),**row,'stale':row['evidence']['signature']!=current['signature']} for row in rows],
                'total':self.collection.count_documents(query),'offset':offset,'limit':limit}

    def save(self, saved, session_token):
        from app.project_cleanup import project_data_lock
        with project_data_lock(self.projects.database) as check_lock:
            access = self.projects.access
            context = None
            try:
                # GPU inference may outlive a role change, logout or disabled account.
                if access:
                    actor = access.authenticate(session_token)
                    if actor.get('must_change_password'):
                        raise HTTPException(403, 'password_change_required')
                    context = actor_context.set(actor)
                self.projects.require_project(saved['project_id'], 'review')
                current = self.evidence(saved['project_id'], saved['run_id'])
                saved['created_by'] = access.review_identity() if access else {}
                check_lock()
                self.collection.create_index([('project_id',1),('run_id',1),('created_at',-1),('_id',1)])
                self.collection.insert_one(saved)
                return {'id':saved.pop('_id'),**saved,'stale':current['signature']!=saved['evidence']['signature']}
            finally:
                if context is not None:
                    actor_context.reset(context)

    async def generate(self, request, project_id, run_id):
        async with self.ai.inspections.slot:
            evidence = await asyncio.to_thread(self.evidence, project_id, run_id)
            result = await self.ai.infer(request, prompt_messages(evidence), INPUT_TOKENS, OUTPUT_TOKENS)
            proposal = validate_conclusion(result.get('text'), evidence)
            self.ai.validate_metrics(result, INPUT_TOKENS, OUTPUT_TOKENS)
            if await request.is_disconnected():
                raise HTTPException(499,'inspection_cancelled')
            saved = {'_id':uuid4().hex,'project_id':str(project_id),'run_id':run_id,'created_at':utc_now(),
                     'scope':'run_conclusion','proposal':proposal,'evidence':evidence,'metrics':result['metrics'],
                     'model':{'id':MODEL['model_id'],'revision':MODEL['revision'],'quantization':'NF4','fine_tuned':False,'file_hashes':MODEL['files']}}
            return await asyncio.to_thread(self.save, saved, request.headers.get('x-bim-session', ''))
