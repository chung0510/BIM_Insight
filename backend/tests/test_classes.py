import asyncio
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from uuid import uuid4

from openpyxl import Workbook, load_workbook

from test_access import access_workspace, actors, account, headers
from test_practice import exercise, source_run, submit


def classroom(client, teacher, code='REVIT-01'):
    response=client.post('/api/practice/classes',headers=headers(teacher),json={
        'code':code,'name':'Thực hành BIM kiến trúc','term':'HK1 2026-2027','description':'Đối chiếu mô hình và hồ sơ.'})
    assert response.status_code==201,response.text
    return response.json()


def add_members(client, teacher, room, *students):
    response=client.post(f"/api/practice/classes/{room['id']}/members",headers=headers(teacher),json={
        'expected_revision':room['revision'],'members':[{'student_id':item['user']['id'],'administrative_class':'22XD1'} for item in students]})
    assert response.status_code==200,response.text
    return response.json()


def promote(client, admin, username, role):
    result=account(client,username)
    response=client.post(f"/api/admin/users/{result['user']['id']}/role",headers=headers(admin),json={'role':role,'expected_revision':result['user']['revision']})
    assert response.status_code==200,response.text
    result['user']=response.json()
    return result


def test_class_ownership_membership_revision_and_archive(access_workspace):
    client,_,_=access_workspace
    admin,user,teacher,student=actors(client)
    other=promote(client,admin,'other_teacher','teacher')
    room=classroom(client,teacher)
    base=f"/api/practice/classes/{room['id']}"
    assert client.get('/api/practice/classes',headers=headers(student)).json()['total']==0
    for actor in [other,student]:
        assert client.get(base,headers=headers(actor)).status_code==404
    for actor in [admin,user]:
        assert client.get('/api/practice/classes',headers=headers(actor)).status_code==403
    duplicate=client.post('/api/practice/classes',headers=headers(teacher),json={key:room[key] for key in ['code','name','term','description']})
    assert duplicate.status_code==409
    room=add_members(client,teacher,room,student)
    assert room['student_count']==1 and room['revision']==2
    own=client.get(base,headers=headers(student)).json()
    assert own['membership']['administrative_class']=='22XD1' and 'student_ids' not in own
    assert client.get(base+'/members',headers=headers(student)).status_code==403
    assert client.post(base+'/members',headers=headers(other),json={'expected_revision':2,'members':[{'student_id':student['user']['id']}]}).status_code==404
    assert client.post(base,headers=headers(teacher),json={'expected_revision':1,'name':'Stale edit'}).status_code==409
    second=classroom(client,teacher,'REVIT-02')
    add_members(client,teacher,second,student)
    assert client.get('/api/practice/classes',headers=headers(student)).json()['total']==2
    archived=client.post(base,headers=headers(teacher),json={'expected_revision':2,'archived':True})
    assert archived.status_code==200,archived.text
    assert client.get('/api/practice/classes?archived=true',headers=headers(student)).json()['total']==1
    assert client.post(base+'/members',headers=headers(teacher),json={'expected_revision':3,'members':[{'student_id':student['user']['id']}]}).status_code==409


def test_class_assignment_snapshot_gradebook_notifications_and_history(access_workspace):
    client,database,_=access_workspace
    admin,_,teacher,student=actors(client)
    late_joiner=promote(client,admin,'late_student','student')
    room=add_members(client,teacher,classroom(client,teacher),student)
    task=exercise(client,teacher,student,class_id=room['id'],student_ids=[],due_at=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat())
    assert task['student_ids']==[student['user']['id']] and task['class_context']['code']=='REVIT-01'
    room=add_members(client,teacher,room,late_joiner)
    assert client.get(f"/api/practice/assignments?class_id={room['id']}",headers=headers(late_joiner)).json()['total']==0
    notices=client.get('/api/practice/notifications',headers=headers(student)).json()
    assert notices['unread']>=2 and notices['upcoming'][0]['assignment_id']==task['id']
    assert client.post(f"/api/practice/notifications/{notices['items'][0]['id']}/read",headers=headers(late_joiner),json={}).status_code==404
    assert client.post(f"/api/practice/notifications/{notices['items'][0]['id']}/read",headers=headers(student),json={}).status_code==200
    gradebook=f"/api/practice/classes/{room['id']}/gradebook?assignment_id={task['id']}"
    before=client.get(gradebook,headers=headers(teacher))
    assert before.status_code==200,before.text
    assert before.json()['total']==1 and before.json()['items'][0]['status']=='not_submitted'
    assert client.get(gradebook,headers=headers(student)).status_code==403
    project,_,run=source_run(client,student)
    record=submit(client,student,task,project,run)
    base=f"/api/practice/submissions/{record['id']}"
    value={'expected_revision':0,'published':True,'feedback':'=unsafe Excel formula',
           'scores':[{'criterion_id':'model','points':5},{'criterion_id':'coordination','points':3}]}
    assert client.post(base+'/grade',headers=headers(teacher),json=value).status_code==200
    row=client.get(gradebook,headers=headers(teacher)).json()['items'][0]
    assert row['status']=='published' and row['published']['grade']['total_points']==8
    newer=submit(client,student,task,project,run)
    row=client.get(gradebook,headers=headers(teacher)).json()['items'][0]
    assert row['status']=='submitted' and row['submission']['id']==newer['id'] and row['published']['id']==record['id']
    exported=client.get(f"/api/practice/classes/{room['id']}/gradebook/export?assignment_id={task['id']}",headers=headers(teacher))
    assert exported.status_code==200,exported.text
    book=load_workbook(BytesIO(exported.content)); sheet=book.active
    assert sheet.max_row==2 and all(cell.data_type!='f' for line in sheet for cell in line)
    assert any(cell.value=='=unsafe Excel formula' for line in sheet for cell in line)
    book.close()
    original=database.practice_submissions.find_one({'_id':record['id']})
    removed=client.post(f"/api/practice/classes/{room['id']}/members/{student['user']['id']}/remove",headers=headers(teacher),json={'expected_revision':room['revision']})
    assert removed.status_code==200,removed.text
    assert client.get(f"/api/practice/classes/{room['id']}",headers=headers(student)).status_code==404
    assert client.get(base,headers=headers(student)).json()['grade']['total_points']==8
    assert client.post(f"/api/practice/assignments/{task['id']}/submissions",headers=headers(student),json={'id':uuid4().hex,'project_id':project['id'],'run_id':run['id']}).status_code==404
    assert database.practice_submissions.find_one({'_id':record['id']})==original


def test_explicit_legacy_attachment_keeps_submitted_snapshot(access_workspace):
    client,database,_=access_workspace
    _,_,teacher,student=actors(client)
    task=exercise(client,teacher,student)
    project,_,run=source_run(client,student)
    record=submit(client,student,task,project,run)
    original=database.practice_submissions.find_one({'_id':record['id']})
    room=add_members(client,teacher,classroom(client,teacher),student)
    response=client.post(f"/api/practice/assignments/{task['id']}/class",headers=headers(teacher),json={'class_id':room['id']})
    assert response.status_code==200,response.text
    assert database.practice_submissions.find_one({'_id':record['id']})==original
    notices=client.get('/api/practice/notifications',headers=headers(student)).json()['items']
    notice=next(item for item in notices if item['kind']=='assignment_created' and item['assignment_id']==task['id'])
    assert notice['class_id']==room['id']
    assert database.practice_notifications.find_one({'_id':notice['id']})['class_id'] is None
    assert client.get(f"/api/practice/assignments?class_id={room['id']}",headers=headers(student)).json()['total']==1
    other=add_members(client,teacher,classroom(client,teacher,'OTHER'),student)
    assert client.post(f"/api/practice/assignments/{task['id']}/class",headers=headers(teacher),json={'class_id':other['id']}).status_code==409
    assert client.get(f"/api/practice/submissions/{record['id']}",headers=headers(student)).json()['class_context']['id']==room['id']


def test_class_roster_excel_matches_accounts_and_rejects_invalid_input(access_workspace):
    client,database,_=access_workspace
    _,_,teacher,student=actors(client)
    database.auth_users.update_one({'_id':student['user']['id']},{'$set':{'identity_code':'000123'}})
    room=classroom(client,teacher)
    url=f"/api/practice/classes/{room['id']}/members/preview"
    def sheet(rows):
        book=Workbook(); active=book.active
        for row in rows: active.append(row)
        data=BytesIO(); book.save(data); book.close()
        return {'file':('roster.xlsx',data.getvalue())}
    valid=client.post(url,headers=headers(teacher),files=sheet([['Mã sinh viên','Lớp hành chính'],['000123','22XD1']]))
    assert valid.status_code==200,valid.text
    assert valid.json()['rows'][0]['student_id']==student['user']['id'] and valid.json()['valid_count']==1
    duplicate=client.post(url,headers=headers(teacher),files=sheet([['Mã sinh viên'],['000123'],['000123'],['unknown']]))
    assert duplicate.status_code==200 and len(duplicate.json()['errors'])==2
    alias=client.post(url,headers=headers(teacher),files=sheet([['Mã sinh viên'],['000123'],['student']]))
    assert alias.status_code==200 and len(alias.json()['errors'])==1 and len(alias.json()['rows'])==1
    formula=client.post(url,headers=headers(teacher),files=sheet([['Mã sinh viên'],['=1+1']]))
    assert formula.status_code==422
    assert database.auth_users.count_documents({'role':'student'})==1


def test_archived_class_does_not_generate_due_reminders(access_workspace):
    client,database,_=access_workspace
    _,_,teacher,student=actors(client)
    room=add_members(client,teacher,classroom(client,teacher),student)
    task=exercise(client,teacher,student,class_id=room['id'],due_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    assert len(client.get('/api/practice/notifications',headers=headers(student)).json()['upcoming'])==1
    response=client.post(f"/api/practice/classes/{room['id']}",headers=headers(teacher),json={'expected_revision':room['revision'],'archived':True})
    assert response.status_code==200,response.text
    assert client.get('/api/practice/notifications',headers=headers(student)).json()['upcoming']==[]
    assert client.get(f"/api/practice/assignments?class_id={room['id']}",headers=headers(student)).json()['total']==1
    assert client.post(f"/api/practice/assignments/{task['id']}/submissions",headers=headers(student),json={'id':uuid4().hex,'project_id':str(uuid4())}).status_code==409


def test_grade_save_and_class_archive_are_serialized(access_workspace,monkeypatch):
    from app.practice import PracticeStore
    from app.classes import ClassStore
    client,_,_=access_workspace
    _,_,teacher,student=actors(client)
    room=add_members(client,teacher,classroom(client,teacher),student)
    task=exercise(client,teacher,student,class_id=room['id'])
    project,_,run=source_run(client,student)
    record=submit(client,student,task,project,run)
    checked,release,archive_started=Event(),Event(),Event()
    writable=PracticeStore.writable_assignment; update=ClassStore.update
    def paused(self,row):
        writable(self,row); checked.set(); assert release.wait(10)
    def archiving(self,*args):
        archive_started.set(); return update(self,*args)
    monkeypatch.setattr(PracticeStore,'writable_assignment',paused)
    monkeypatch.setattr(ClassStore,'update',archiving)
    with ThreadPoolExecutor(max_workers=2) as pool:
        grading=pool.submit(client.post,f"/api/practice/submissions/{record['id']}/grade",headers=headers(teacher),json={
            'expected_revision':0,'published':True,'scores':[{'criterion_id':'model','points':5},{'criterion_id':'coordination','points':3}]})
        assert checked.wait(10)
        archiving_job=pool.submit(client.post,f"/api/practice/classes/{room['id']}",headers=headers(teacher),json={'expected_revision':room['revision'],'archived':True})
        assert archive_started.wait(10)
        blocked=False
        try:
            attempt=archiving_job.result(timeout=.3)
            blocked=attempt.status_code==409 and attempt.json()['detail']=='project_busy'
        except TimeoutError:
            blocked=True
        finally:
            release.set()
        assert grading.result(timeout=10).status_code==200
        attempted=archiving_job.result(timeout=10)
        assert attempted.status_code in {200,409}
    assert blocked,'Class must not archive while the checked grade is not saved.'
    if attempted.status_code==409:
        retry=client.post(f"/api/practice/classes/{room['id']}",headers=headers(teacher),json={'expected_revision':room['revision'],'archived':True})
        assert retry.status_code==200,retry.text


def test_archiving_during_qwen_keeps_analysis_unsaved(access_workspace,monkeypatch):
    from app.ai import AiService
    client,database,_=access_workspace
    _,_,teacher,student=actors(client)
    room=add_members(client,teacher,classroom(client,teacher),student)
    task=exercise(client,teacher,student,class_id=room['id'])
    project,_,run=source_run(client,student)
    record=submit(client,student,task,project,run)
    async def infer(self,request,messages,*limits):
        response=await asyncio.to_thread(client.post,f"/api/practice/classes/{room['id']}",headers=headers(teacher),json={'expected_revision':room['revision'],'archived':True})
        assert response.status_code==200,response.text
        facts=json.loads(messages[1]['content'])
        return {'text':json.dumps({'assessment':facts['assessment'],'summary':'Cần đối chiếu hình học trước khi xác nhận kết quả.',
                'priorities':[{'group_id':'g1','action':'verify_geometry','rationale':'Kiểm tra minh chứng và ý đồ thiết kế.'}],
                'next_steps':['review_design_intent'],'citations':['stats','g1'],'requires_review':True}),
                'metrics':{'weights_verified':True,'input_tokens':435,'output_tokens':90,'elapsed_seconds':1.}}
    monkeypatch.setattr(AiService,'infer',infer)
    response=client.post(f"/api/practice/submissions/{record['id']}/analysis",headers=headers(teacher),json={})
    assert response.status_code==409 and response.json()['detail']=='class_archived'
    saved=database.practice_submissions.find_one({'_id':record['id']})
    assert 'analysis' not in saved and saved['grade'] is None
