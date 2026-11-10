import asyncio
from datetime import datetime, timezone
import re
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.access import actor_context
from app.ai import MODEL
from app.project_cleanup import project_data_lock
from app.projects import utc_now
from app.run_conclusions import build_evidence, prompt_messages, validate_conclusion, INPUT_TOKENS, OUTPUT_TOKENS


class Criterion(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(pattern=r'^[a-z0-9_-]{1,48}$')
    title: str = Field(min_length=2, max_length=160)
    max_points: float = Field(gt=0, le=1000, allow_inf_nan=False)
    description: str = Field(default='', max_length=1500)


class AssignmentCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=160)
    instructions: str = Field(min_length=2, max_length=10000)
    group_name: str = Field(default='', max_length=100)
    due_at: AwareDatetime | None = None
    class_id: str | None = Field(default=None,pattern=r'^[a-f0-9]{32}$')
    class_revision: int | None = Field(default=None,ge=1,le=1000000)
    student_ids: list[str] = Field(default_factory=list, max_length=200)
    criteria: list[Criterion] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def unique_members_and_criteria(self):
        if not self.class_id and not self.student_ids:
            raise ValueError('Recipients are required')
        if len(set(self.student_ids)) != len(self.student_ids) or any(not re.fullmatch(r'[a-f0-9]{32}', item) for item in self.student_ids):
            raise ValueError('Student IDs must be unique account IDs')
        if len({item.id for item in self.criteria}) != len(self.criteria) or sum(item.max_points for item in self.criteria) > 1000:
            raise ValueError('Invalid rubric')
        return self


class SubmissionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    project_id: UUID
    run_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')


class CriterionScore(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    criterion_id: str = Field(pattern=r'^[a-z0-9_-]{1,48}$')
    points: float = Field(ge=0, le=1000, allow_inf_nan=False)
    comment: str = Field(default='', max_length=2000)


class GradeCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_revision: int = Field(ge=0, le=1000000)
    published: bool = False
    feedback: str = Field(default='', max_length=4000)
    scores: list[CriterionScore] = Field(min_length=1, max_length=20)


class PracticeStore:
    def __init__(self, projects, ai):
        self.projects, self.access, self.db, self.ai = projects, projects.access, projects.database, ai
        from app.classes import ClassStore
        self.classes = ClassStore(self)

    def role(self, expected=None):
        role = self.access.actor['role']
        if role not in ({expected} if expected else {'teacher', 'student'}):
            raise HTTPException(403, 'practice_role_required')
        return role

    def assignment(self, identifier):
        role = self.role()
        row = self.db.practice_assignments.find_one({'_id':identifier})
        uid = self.access.actor['id']
        if row is None or not (row['teacher_id'] == uid if role == 'teacher' else uid in row['student_ids']):
            raise HTTPException(404, 'practice_not_found')
        if role=='student' and row.get('class_id') and not self.classes.is_member(row['class_id'],uid):
            raise HTTPException(404,'practice_not_found')
        return row

    def class_contexts(self, rows):
        ids=list({row.get('class_id') for row in rows if row.get('class_id')})
        return {row['_id']:self.classes.context(row) for row in self.db.practice_classes.find({'_id':{'$in':ids}})}

    def public_assignment(self, row, contexts=None):
        contexts=self.class_contexts([row]) if contexts is None else contexts
        result = {'id':row['_id'], **{key:value for key,value in row.items() if key != '_id'},'class_context':contexts.get(row.get('class_id'))}
        if self.access.actor['role'] == 'student':
            result.pop('student_ids', None)
            result.pop('students', None)
        return result

    def students(self, query, offset, limit):
        self.role('teacher')
        where = {'role':'student', 'disabled':False}
        if query:
            pattern = {'$regex':re.escape(query), '$options':'i'}
            where['$or'] = [{key:pattern} for key in ['username','display_name','identity_code']]
        collection = self.db.auth_users
        rows = collection.find(where, {'username':1,'display_name':1,'identity_code':1}).sort('username',1).skip(offset).limit(limit)
        return {'items':[{'id':row.pop('_id'),**row} for row in rows], 'total':collection.count_documents(where), 'offset':offset, 'limit':limit}

    def create_assignment(self, payload):
        self.role('teacher')
        with project_data_lock(self.db) as check_lock:
            if payload.class_id:
                room=self.classes.require(payload.class_id,True)
                if payload.class_revision is not None:
                    self.classes.check_revision(room,payload.class_revision)
                members=self.classes.active_ids(payload.class_id)
                recipients=payload.student_ids or members
                if not recipients or len(recipients)>200 or not set(recipients)<=set(members):
                    raise HTTPException(422,'class_assignment_recipients')
                payload=payload.model_copy(update={'student_ids':recipients})
            check_lock()
            return self._create_assignment(payload)

    def _create_assignment(self, payload):
        self.role('teacher')
        members = list(self.db.auth_users.find({'_id':{'$in':payload.student_ids},'role':'student','disabled':False}, {'username':1,'display_name':1,'identity_code':1}))
        if len(members) != len(payload.student_ids):
            raise HTTPException(422, 'practice_students_invalid')
        actor = self.access.actor
        data = payload.model_dump(mode='json')
        if payload.due_at:
            data['due_at'] = payload.due_at.astimezone(timezone.utc).isoformat()
        row = {'_id':uuid4().hex, **data, 'teacher_id':actor['id'], 'teacher_name':actor['display_name'],
               'students':[{'id':item.pop('_id'),**item} for item in members], 'created_at':utc_now(),
               'max_points':round(sum(item.max_points for item in payload.criteria),2)}
        self.db.practice_assignments.create_index([('teacher_id',1),('created_at',-1)])
        self.db.practice_assignments.create_index([('student_ids',1),('created_at',-1)])
        self.db.practice_assignments.create_index([('class_id',1),('created_at',-1)])
        self.db.practice_assignments.insert_one(row)
        self.access.audit(actor['id'],'practice_assigned',row['_id'])
        for recipient in payload.student_ids:
            self.classes.notify(recipient,'assignment_created',row['_id'],'Bài thực hành mới',row['title'],assignment_id=row['_id'],class_id=payload.class_id)
        return self.public_assignment(row)

    def assignment_filter(self, class_id=None, unassigned=False):
        role, uid = self.role(), self.access.actor['id']
        where = {'teacher_id':uid} if role == 'teacher' else {'student_ids':uid}
        if role=='student':
            where['$or']=[{'class_id':None},{'class_id':{'$in':self.classes.student_class_ids()}}]
        if class_id:
            self.classes.require(class_id)
            where['class_id']=class_id
        elif unassigned:
            where['class_id']=None
        return where

    def assignments(self, offset, limit, class_id=None, unassigned=False):
        role, uid = self.role(), self.access.actor['id']
        where=self.assignment_filter(class_id,unassigned)
        rows = list(self.db.practice_assignments.find(where).sort([('created_at',-1),('_id',1)]).skip(offset).limit(limit))
        contexts=self.class_contexts(rows)
        query = {'assignment_id':{'$in':[row['_id'] for row in rows]}}
        if role == 'student':
            query['student_id'] = uid
        counts = {row['_id']:row for row in self.db.practice_submissions.aggregate([
            {'$match':query}, {'$group':{'_id':'$assignment_id','submitted':{'$sum':1},
             'published':{'$sum':{'$cond':[{'$eq':['$grade.published',True]},1,0]}}}}])}
        return {'items':[{**self.public_assignment(row,contexts), 'submission_count':counts.get(row['_id'],{}).get('submitted',0),
                          'published_count':counts.get(row['_id'],{}).get('published',0)} for row in rows],
                'total':self.db.practice_assignments.count_documents(where),'offset':offset,'limit':limit}

    def require_submission(self, identifier):
        role, uid = self.role(), self.access.actor['id']
        row = self.db.practice_submissions.find_one({'_id':identifier,'teacher_id' if role == 'teacher' else 'student_id':uid})
        if row is None:
            raise HTTPException(404, 'practice_not_found')
        return row

    def summary(self):
        role, uid = self.role(), self.access.actor['id']
        assignments = self.assignment_filter()
        submissions = {'teacher_id' if role == 'teacher' else 'student_id':uid}
        return {'assignments':self.db.practice_assignments.count_documents(assignments),
                'submissions':self.db.practice_submissions.count_documents(submissions),
                'pending':self.db.practice_submissions.count_documents({**submissions,'grade.published':{'$ne':True}}),
                'published':self.db.practice_submissions.count_documents({**submissions,'grade.published':True}),
                'classes':self.db.practice_classes.count_documents({'teacher_id':uid,'archived':False} if role=='teacher' else {'_id':{'$in':self.classes.student_class_ids()},'archived':False}),
                'unread':self.db.practice_notifications.count_documents({'user_id':uid,'read_at':None})}

    def submission_contexts(self, rows):
        tasks=list(self.db.practice_assignments.find({'_id':{'$in':[row['assignment_id'] for row in rows]}},{'class_id':1}))
        contexts=self.class_contexts(tasks)
        return {task['_id']:contexts.get(task.get('class_id')) for task in tasks}

    def public_submission(self, row, contexts=None):
        contexts=self.submission_contexts([row]) if contexts is None else contexts
        result = {'id':row['_id'], **{key:value for key,value in row.items() if key not in {'_id','request'}},'class_context':contexts.get(row['assignment_id'])}
        if self.access.actor['role'] == 'student':
            if not (result.get('grade') or {}).get('published'):
                result['grade'] = None
            result.pop('analysis',None)
        return result

    def submissions(self, offset, limit, assignment_id=None, published=None, class_id=None):
        role, uid = self.role(), self.access.actor['id']
        query = {'teacher_id' if role == 'teacher' else 'student_id':uid}
        if published is not None:
            query['grade.published'] = True if published else {'$ne':True}
        if assignment_id:
            self.assignment(assignment_id)
            query['assignment_id'] = assignment_id
        if class_id:
            self.classes.require(class_id)
            ids=[row['_id'] for row in self.db.practice_assignments.find({'class_id':class_id},{'_id':1})]
            if assignment_id and assignment_id not in ids: raise HTTPException(404,'practice_not_found')
            query['assignment_id']=assignment_id if assignment_id else {'$in':ids}
        rows = list(self.db.practice_submissions.find(query, {'analysis':0}).sort([('created_at',-1),('_id',1)]).skip(offset).limit(limit))
        contexts=self.submission_contexts(rows)
        return {'items':[self.public_submission(row,contexts) for row in rows], 'total':self.db.practice_submissions.count_documents(query),'offset':offset,'limit':limit}

    def writable_assignment(self, row):
        if row.get('class_id') and self.classes.require(row['class_id'])['archived']:
            raise HTTPException(409,'class_archived')

    def submit(self, assignment_id, payload):
        self.role('student')
        with project_data_lock(self.db) as check_lock:
            task = self.assignment(assignment_id)
            request = {'project_id':str(payload.project_id),'run_id':payload.run_id,'assignment_id':assignment_id,'student_id':self.access.actor['id']}
            existing = self.db.practice_submissions.find_one({'_id':payload.id})
            if existing:
                if existing.get('request') != request:
                    raise HTTPException(409,'practice_submission_changed')
                return self.public_submission(existing)
            self.writable_assignment(task)
            project = self.projects.require_project(payload.project_id,'edit')
            if project.get('owner_id') != self.access.actor['id']:
                raise HTTPException(403,'project_permission_denied')
            run = None
            if payload.run_id:
                restored = self.projects.restore_run(payload.project_id,payload.run_id)
                reports, run = restored['inspections'], restored['report']
                if run['status'] == 'failed':
                    raise HTTPException(409,'practice_evidence_required')
            else:
                latest = self.projects.inspections(payload.project_id,0,200)
                if latest['total'] > 200:
                    raise HTTPException(409,'practice_evidence_required')
                reports = latest['items']
            if not reports or any(item['status']=='failed' for item in reports):
                raise HTTPException(409,'practice_evidence_required')
            fields = ('id','name','kind','sha256','size_bytes','report_url','status','discipline')
            actor = self.access.actor
            count = self.db.practice_submissions.count_documents({'assignment_id':assignment_id,'student_id':actor['id']})
            row = {'_id':payload.id, **request, 'request':request, 'teacher_id':task['teacher_id'],
                   'assignment':{key:task[key] for key in ['title','instructions','group_name','due_at','criteria','max_points','teacher_name']},
                   'project_name':project['name'],'student_name':actor['display_name'],'student_code':actor.get('identity_code') or actor['username'],
                   'attempt':count+1,'created_at':utc_now(),'late':bool(task['due_at'] and datetime.now(timezone.utc)>datetime.fromisoformat(task['due_at'])),
                   'files':[{key:item.get(key) for key in fields} for item in reports], 'source_ids':[item['id'] for item in reports],
                   'run_status':run['status'] if run else None, 'issue_count':len(run['issues']) if run else None, 'grade':None}
            self.db.practice_submissions.create_index([('teacher_id',1),('created_at',-1)])
            self.db.practice_submissions.create_index([('student_id',1),('created_at',-1)])
            self.db.practice_submissions.create_index([('teacher_id',1),('source_ids',1)])
            self.db.practice_submissions.create_index([('project_id',1)])
            check_lock()
            self.db.practice_submissions.insert_one(row)
            self.access.audit(actor['id'],'practice_submitted',row['_id'])
            self.classes.notify(task['teacher_id'],'submission_created',row['_id'],'Có bài nộp mới',task['title'],submission_id=row['_id'],class_id=task.get('class_id'))
            return self.public_submission(row)

    def evidence(self, identifier):
        row = self.require_submission(identifier)
        reports = [self.projects.read_report(item['id']) for item in row['files']]
        if any(item['sha256'] != manifest['sha256'] for item,manifest in zip(reports,row['files'])):
            raise HTTPException(409,'project_artifact_missing')
        run = self.projects.read_report(row['run_id'],'clashes') if row['run_id'] else None
        return {'reports':reports, 'run':run}

    def source_file(self, identifier, report_id):
        row = self.require_submission(identifier)
        file = next((item for item in row['files'] if item['id']==report_id),None)
        if file is None:
            raise HTTPException(404,'report_not_found')
        if not re.fullmatch(r'[a-f0-9]{64}',file['sha256']) or file['kind'] not in {'ifc','pdf','dxf','dwg'}:
            raise HTTPException(409,'project_artifact_missing')
        relative = f"cache/models/{file['sha256']}.ifc" if file['kind']=='ifc' else f"cache/files/{file['sha256']}.{file['kind']}"
        path = self.projects.ensure_local(relative)
        if not path.is_file():
            raise HTTPException(409,'project_artifact_missing')
        return path, file['name']

    def grade(self, identifier, payload):
        self.role('teacher')
        with project_data_lock(self.db) as check_lock:
            check_lock()
            return self._grade(identifier,payload)

    def _grade(self, identifier, payload):
        self.role('teacher')
        row = self.require_submission(identifier)
        self.writable_assignment(self.assignment(row['assignment_id']))
        if (row.get('grade') or {}).get('published') and not payload.published:
            raise HTTPException(409,'practice_grade_published')
        criteria = {item['id']:item for item in row['assignment']['criteria']}
        if len(payload.scores) != len(criteria) or {item.criterion_id for item in payload.scores} != set(criteria) or any(item.points > criteria[item.criterion_id]['max_points'] for item in payload.scores):
            raise HTTPException(422,'practice_score_invalid')
        value = {**payload.model_dump(exclude={'expected_revision'}), 'revision':payload.expected_revision+1,
                 'total_points':round(sum(item.points for item in payload.scores),2),'max_points':row['assignment']['max_points'],
                 **self.access.review_identity(),'updated_at':utc_now()}
        query = {'_id':identifier,'teacher_id':self.access.actor['id'],
                 'grade.revision':payload.expected_revision} if payload.expected_revision else {'_id':identifier,'teacher_id':self.access.actor['id'],'grade':None}
        if not self.db.practice_submissions.update_one(query,{'$set':{'grade':value}}).matched_count:
            raise HTTPException(409,'practice_grade_changed')
        self.access.audit(self.access.actor['id'],'practice_grade_published' if payload.published else 'practice_grade_saved',identifier)
        if payload.published:
            task=self.db.practice_assignments.find_one({'_id':row['assignment_id']})
            self.classes.notify(row['student_id'],'grade_published',identifier+':'+str(value['revision']),'Điểm và phản hồi đã công bố',row['assignment']['title'],submission_id=identifier,class_id=task.get('class_id'))
        return value

    async def analyze(self, request, identifier):
        self.role('teacher')
        async with self.ai.inspections.slot:
            row = await asyncio.to_thread(self.require_submission,identifier)
            await asyncio.to_thread(lambda:self.writable_assignment(self.assignment(row['assignment_id'])))
            if not row['run_id']:
                raise HTTPException(409,'ai_summary_no_evidence')
            report = await asyncio.to_thread(self.projects.read_report,row['run_id'],'clashes')
            evidence = build_evidence(report,[])
            result = await self.ai.infer(request,prompt_messages(evidence),INPUT_TOKENS,OUTPUT_TOKENS)
            proposal = validate_conclusion(result.get('text'),evidence)
            self.ai.validate_metrics(result,INPUT_TOKENS,OUTPUT_TOKENS)
            if await request.is_disconnected():
                raise HTTPException(499,'inspection_cancelled')
            def save():
                with project_data_lock(self.db) as check_lock:
                    check_lock()
                    return save_locked()
            def save_locked():
                actor = self.access.authenticate(request.headers.get('x-bim-session',''))
                if actor.get('must_change_password'):
                    raise HTTPException(403,'password_change_required')
                context = actor_context.set(actor)
                try:
                    self.role('teacher')
                    self.require_submission(identifier)
                    self.writable_assignment(self.assignment(row['assignment_id']))
                    analysis = {'proposal':proposal,'evidence':evidence,'metrics':result['metrics'],'created_at':utc_now(),
                                'model':{'id':MODEL['model_id'],'revision':MODEL['revision'],'fine_tuned':False,'quantization':'NF4'},
                                **self.access.review_identity()}
                    self.db.practice_submissions.update_one({'_id':identifier,'teacher_id':self.access.actor['id']},{'$set':{'analysis':analysis}})
                    return analysis
                finally:
                    actor_context.reset(context)
            return await asyncio.to_thread(save)
