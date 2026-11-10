from datetime import datetime, timedelta, timezone
import re
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pymongo.errors import DuplicateKeyError

from app.project_cleanup import project_data_lock
from app.projects import utc_now


class ClassCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    code: str = Field(min_length=2, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=2, max_length=160)
    term: str = Field(min_length=2, max_length=100)
    description: str = Field(default='', max_length=4000)


class Revision(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_revision: int = Field(ge=1, le=1000000)


class ClassChange(Revision):
    code: str | None = Field(default=None, min_length=2, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    name: str | None = Field(default=None, min_length=2, max_length=160)
    term: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    archived: bool | None = None


class ClassMember(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    student_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    administrative_class: str = Field(default='', max_length=100)


class MembersChange(Revision):
    members: list[ClassMember] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def unique(self):
        if len({item.student_id for item in self.members}) != len(self.members):
            raise ValueError('Duplicate student IDs')
        return self


class AssignmentClass(BaseModel):
    model_config = ConfigDict(extra='forbid')
    class_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class ClassStore:
    def __init__(self, practice):
        self.practice, self.db, self.access = practice, practice.db, practice.access

    def require(self, identifier, edit=False):
        role = self.practice.role('teacher' if edit else None)
        row = self.db.practice_classes.find_one({'_id':identifier})
        uid = self.access.actor['id']
        allowed = row is not None and (row['teacher_id']==uid if role=='teacher' else self.is_member(identifier,uid))
        if not allowed:
            raise HTTPException(404,'class_not_found')
        if edit and row['archived']:
            raise HTTPException(409,'class_archived')
        return row

    def is_member(self, identifier, uid):
        return bool(self.db.practice_class_members.find_one({'class_id':identifier,'student_id':uid,'active':True},{'_id':1}))

    def active_ids(self, identifier):
        return [row['student_id'] for row in self.db.practice_class_members.find({'class_id':identifier,'active':True},{'student_id':1}).sort('student_id',1)]

    def student_class_ids(self):
        return self.db.practice_class_members.distinct('class_id',{'student_id':self.access.actor['id'],'active':True})

    def context(self, row):
        return {'id':row['_id'], **{key:row[key] for key in ['code','name','term','archived']}}

    def public_many(self, rows):
        if not rows:
            return []
        ids=[row['_id'] for row in rows]
        counts={row['_id']:row['count'] for row in self.db.practice_class_members.aggregate([
            {'$match':{'class_id':{'$in':ids},'active':True}}, {'$group':{'_id':'$class_id','count':{'$sum':1}}}])}
        where={'class_id':{'$in':ids}}
        student=self.access.actor['role']=='student'
        if student:
            where['student_ids']=self.access.actor['id']
        tasks=list(self.db.practice_assignments.find(where,{'class_id':1}))
        task_classes={row['_id']:row['class_id'] for row in tasks}
        query={'assignment_id':{'$in':list(task_classes)}}
        if student:
            query['student_id']=self.access.actor['id']
        totals={identifier:{'assignment_count':0,'submission_count':0,'pending_count':0,'published_count':0} for identifier in ids}
        for row in tasks:
            totals[row['class_id']]['assignment_count']+=1
        for row in self.db.practice_submissions.aggregate([{'$match':query},{'$group':{'_id':'$assignment_id','count':{'$sum':1},'published':{'$sum':{'$cond':[{'$eq':['$grade.published',True]},1,0]}}}}]):
            item=totals[task_classes[row['_id']]]
            item['submission_count']+=row['count']; item['published_count']+=row['published']; item['pending_count']+=row['count']-row['published']
        memberships={row['class_id']:row for row in self.db.practice_class_members.find({'class_id':{'$in':ids},'student_id':self.access.actor['id'],'active':True})} if student else {}
        names={row['_id']:row['display_name'] for row in self.db.auth_users.find({'_id':{'$in':[item['teacher_id'] for item in rows]}},{'display_name':1})}
        result=[]
        for row in rows:
            item={'id':row['_id'],**{key:value for key,value in row.items() if key not in {'_id','term_key'}},
                  'teacher_name':names.get(row['teacher_id'],row['teacher_name']), 'student_count':counts.get(row['_id'],0),**totals[row['_id']]}
            if student:
                member=memberships.get(row['_id'],{})
                item['membership']={key:member.get(key,'') for key in ['administrative_class','added_at']}
            result.append(item)
        return result

    def detail(self, identifier):
        return self.public_many([self.require(identifier)])[0]

    def listing(self, archived, query, offset, limit):
        role=self.practice.role(); where={'teacher_id':self.access.actor['id']} if role=='teacher' else {'_id':{'$in':self.student_class_ids()}}
        if archived is not None:
            where['archived']=archived
        if query:
            pattern={'$regex':re.escape(query),'$options':'i'}
            where['$or']=[{key:pattern} for key in ['code','name','term']]
        rows=list(self.db.practice_classes.find(where).sort([('created_at',-1),('_id',1)]).skip(offset).limit(limit))
        return {'items':self.public_many(rows),'total':self.db.practice_classes.count_documents(where),'offset':offset,'limit':limit}

    def create(self, payload):
        self.practice.role('teacher'); actor=self.access.actor
        row={'_id':uuid4().hex,**payload.model_dump(),'code':payload.code.upper(),'term_key':payload.term.casefold(),
             'teacher_id':actor['id'],'teacher_name':actor['display_name'],'archived':False,'revision':1,'created_at':utc_now(),'updated_at':utc_now()}
        self.db.practice_classes.create_index([('teacher_id',1),('code',1),('term_key',1)],unique=True)
        self.db.practice_classes.create_index([('teacher_id',1),('archived',1),('created_at',-1)])
        try:
            self.db.practice_classes.insert_one(row)
        except DuplicateKeyError:
            raise HTTPException(409,'class_code_exists') from None
        self.access.audit(actor['id'],'class_created',row['_id'])
        return self.public_many([row])[0]

    def check_revision(self, row, expected):
        if row['revision']!=expected:
            raise HTTPException(409,'class_changed')

    def update(self, identifier, payload):
        self.practice.role('teacher')
        with project_data_lock(self.db) as check_lock:
            row=self.require(identifier); self.check_revision(row,payload.expected_revision)
            if row['archived'] and payload.archived is not False:
                raise HTTPException(409,'class_archived')
            values=payload.model_dump(exclude={'expected_revision'},exclude_none=True)
            if 'code' in values: values['code']=values['code'].upper()
            if 'term' in values: values['term_key']=values['term'].casefold()
            values['updated_at']=utc_now(); check_lock()
            try:
                changed=self.db.practice_classes.update_one({'_id':identifier,'revision':payload.expected_revision},{'$set':values,'$inc':{'revision':1}})
            except DuplicateKeyError:
                raise HTTPException(409,'class_code_exists') from None
            if not changed.matched_count:
                raise HTTPException(409,'class_changed')
        self.access.audit(self.access.actor['id'],'class_updated',identifier)
        return self.detail(identifier)

    def members(self, identifier, query, offset, limit):
        self.practice.role('teacher'); self.require(identifier)
        where={'class_id':identifier,'active':True}
        if query:
            pattern={'$regex':re.escape(query),'$options':'i'}
            where['student_id']={'$in':[row['_id'] for row in self.db.auth_users.find({'$or':[{key:pattern} for key in ['username','display_name','identity_code']]},{'_id':1})]}
        rows=list(self.db.practice_class_members.find(where).sort([('added_at',1),('student_id',1)]).skip(offset).limit(limit))
        users={row['_id']:row for row in self.db.auth_users.find({'_id':{'$in':[row['student_id'] for row in rows]}},{'username':1,'display_name':1,'identity_code':1,'disabled':1,'role':1})}
        items=[{'id':row['student_id'],**{key:value for key,value in users.get(row['student_id'],{}).items() if key!='_id'},
                'administrative_class':row.get('administrative_class',''),'added_at':row['added_at'],'active':True} for row in rows]
        return {'items':items,'total':self.db.practice_class_members.count_documents(where),'offset':offset,'limit':limit}

    def add_members(self, identifier, payload):
        with project_data_lock(self.db) as check_lock:
            room=self.require(identifier,True); self.check_revision(room,payload.expected_revision)
            ids=[item.student_id for item in payload.members]
            users={row['_id']:row for row in self.db.auth_users.find({'_id':{'$in':ids},'role':'student','disabled':False},{'_id':1})}
            if len(users)!=len(ids):
                raise HTTPException(422,'practice_students_invalid')
            self.db.practice_class_members.create_index([('class_id',1),('student_id',1)],unique=True)
            self.db.practice_class_members.create_index([('student_id',1),('active',1)])
            check_lock()
            for item in payload.members:
                old=self.db.practice_class_members.find_one({'class_id':identifier,'student_id':item.student_id})
                values={**item.model_dump(),'administrative_class':item.administrative_class or (old or {}).get('administrative_class',''),
                        'class_id':identifier,'active':True,'added_at':old['added_at'] if old and old['active'] else utc_now()}
                self.db.practice_class_members.update_one({'class_id':identifier,'student_id':item.student_id},{'$set':values,'$unset':{'removed_at':''}},upsert=True)
                if not old or not old['active']:
                    self.notify(item.student_id,'class_added',identifier+':'+str(room['revision']),f"Bạn được thêm vào lớp {room['code']}",room['name'],class_id=identifier)
            self.db.practice_classes.update_one({'_id':identifier,'revision':payload.expected_revision},{'$inc':{'revision':1},'$set':{'updated_at':utc_now()}})
        self.access.audit(self.access.actor['id'],'class_members_added',identifier)
        return self.detail(identifier)

    def remove_member(self, identifier, student_id, payload):
        with project_data_lock(self.db) as check_lock:
            row=self.require(identifier,True); self.check_revision(row,payload.expected_revision); check_lock()
            changed=self.db.practice_class_members.update_one({'class_id':identifier,'student_id':student_id,'active':True},{'$set':{'active':False,'removed_at':utc_now()}})
            if not changed.matched_count:
                raise HTTPException(404,'class_member_not_found')
            self.db.practice_classes.update_one({'_id':identifier,'revision':payload.expected_revision},{'$inc':{'revision':1},'$set':{'updated_at':utc_now()}})
        self.access.audit(self.access.actor['id'],'class_member_removed',identifier)
        return self.detail(identifier)

    def notify(self, recipient, kind, target, title, body, **context):
        self.db.practice_notifications.create_index([('user_id',1),('created_at',-1)])
        self.db.practice_notifications.update_one({'_id':f'{kind}:{target}:{recipient}'},{'$setOnInsert':{'user_id':recipient,'kind':kind,'title':title,'body':body,
            'created_at':utc_now(),'read_at':None,**context}},upsert=True)

    def notifications(self, offset, limit):
        role=self.practice.role(); uid=self.access.actor['id']; where={'user_id':uid}
        rows=list(self.db.practice_notifications.find(where).sort([('created_at',-1),('_id',1)]).skip(offset).limit(limit))
        # An old assignment event keeps its original payload; navigation follows its current class.
        parents={row['_id']:row.get('class_id') for row in self.db.practice_assignments.find({'_id':{'$in':[item['assignment_id'] for item in rows if item.get('assignment_id')]}},{'class_id':1})}
        for row in rows:
            if row.get('assignment_id') in parents:
                row['class_id']=parents[row['assignment_id']]
        tasks={'teacher_id':uid} if role=='teacher' else self.practice.assignment_filter()
        tasks['class_id']={'$nin':[row['_id'] for row in self.db.practice_classes.find({'archived':True},{'_id':1})]}
        now=datetime.now(timezone.utc)
        tasks['due_at']={'$gte':now.isoformat(),'$lte':(now+timedelta(days=7)).isoformat()}
        candidates=list(self.db.practice_assignments.find(tasks,{'class_id':1,'title':1,'due_at':1}).sort('due_at',1))
        submitted=set(self.db.practice_submissions.distinct('assignment_id',{'student_id':uid,'assignment_id':{'$in':[item['_id'] for item in candidates]}})) if role=='student' else set()
        upcoming=[{'assignment_id':task['_id'],'class_id':task.get('class_id'),'title':task['title'],'due_at':task['due_at']} for task in candidates if task['_id'] not in submitted][:5]
        return {'items':[{'id':row.pop('_id'),**row} for row in rows],'total':self.db.practice_notifications.count_documents(where),
                'unread':self.db.practice_notifications.count_documents({**where,'read_at':None}),'upcoming':upcoming,'offset':offset,'limit':limit}

    def read_notification(self, identifier):
        self.practice.role()
        if not self.db.practice_notifications.update_one({'_id':identifier,'user_id':self.access.actor['id']},{'$set':{'read_at':utc_now()}}).matched_count:
            raise HTTPException(404,'notification_not_found')
        return {'status':'read'}

    def attach_assignment(self, assignment_id, payload):
        self.practice.role('teacher')
        with project_data_lock(self.db) as check_lock:
            room=self.require(payload.class_id,True); task=self.practice.assignment(assignment_id)
            if task.get('class_id'):
                if task['class_id']!=payload.class_id: raise HTTPException(409,'class_assignment_attached')
                return self.practice.public_assignment(task)
            if not set(task['student_ids'])<=set(self.active_ids(payload.class_id)):
                raise HTTPException(422,'class_assignment_members_missing')
            check_lock()
            self.db.practice_assignments.update_one({'_id':assignment_id,'class_id':None},{'$set':{'class_id':payload.class_id}})
            self.access.audit(self.access.actor['id'],'class_assignment_attached',assignment_id)
        return self.practice.public_assignment(self.db.practice_assignments.find_one({'_id':assignment_id}))

    def gradebook(self, identifier, assignment_id, offset=0, limit=50):
        self.practice.role('teacher'); room=self.require(identifier); task=self.practice.assignment(assignment_id)
        if task.get('class_id')!=identifier:
            raise HTTPException(404,'practice_not_found')
        ids=sorted(task['student_ids']); selected=ids[offset:offset+limit]
        users={row['_id']:row for row in self.db.auth_users.find({'_id':{'$in':selected}},{'username':1,'display_name':1,'identity_code':1})}
        snapshots={row['id']:row for row in task['students']}
        members={row['student_id']:row for row in self.db.practice_class_members.find({'class_id':identifier,'student_id':{'$in':selected}})}
        histories=self.db.practice_submissions.find({'assignment_id':assignment_id,'student_id':{'$in':selected}},{'analysis':0}).sort([('created_at',-1),('_id',-1)])
        latest,published,counts={},{},{}
        context={assignment_id:self.context(room)}
        for row in histories:
            uid=row['student_id']; counts[uid]=counts.get(uid,0)+1
            if uid not in latest: latest[uid]=self.practice.public_submission(row,context)
            if uid not in published and (row.get('grade') or {}).get('published'): published[uid]=self.practice.public_submission(row,context)
        rows=[]
        for uid in selected:
            user=users.get(uid,snapshots[uid]); member=members.get(uid,{})
            submission=latest.get(uid); grade=(submission or {}).get('grade')
            rows.append({'student_id':uid,'student_name':user['display_name'],'student_code':user.get('identity_code') or user['username'],
                         'administrative_class':member.get('administrative_class',''),'active':member.get('active',False),
                         'status':'not_submitted' if submission is None else 'published' if grade and grade['published'] else 'draft' if grade else 'submitted',
                         'submission':submission,'published':published.get(uid),'attempt_count':counts.get(uid,0)})
        return {'items':rows,'total':len(ids),'offset':offset,'limit':limit,'assignment':self.practice.public_assignment(task),'class_context':self.context(room)}

    def export_gradebook(self, identifier, assignment_id):
        from app.provisioning import spreadsheet
        data=self.gradebook(identifier,assignment_id,0,200)
        labels={'not_submitted':'Chưa nộp','submitted':'Đã nộp, chờ chấm','draft':'Có nháp đánh giá','published':'Đã công bố'}
        rows=[]
        for item in data['items']:
            published=item['published']; grade=(published or {}).get('grade')
            rows.append([data['class_context']['code'],data['class_context']['term'],item['student_code'],item['student_name'],item['administrative_class'],
                         data['assignment']['title'],labels[item['status']],item['attempt_count'],(item['submission'] or {}).get('attempt',''),
                         published['attempt'] if published else '',grade['total_points'] if grade else '',data['assignment']['max_points'],grade['feedback'] if grade else '',
                         'Đang tham gia' if item['active'] else 'Đã rời lớp'])
        return spreadsheet(['Mã lớp','Học kỳ','Mã sinh viên','Họ và tên','Lớp hành chính','Bài thực hành','Trạng thái lần mới nhất','Số lần nộp','Lần mới nhất',
                            'Lần đã công bố','Điểm đã công bố','Điểm tối đa','Phản hồi đã công bố','Thành viên'],rows)
