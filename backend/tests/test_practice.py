import asyncio
import json
from uuid import uuid4
import pytest

from app.demo import demo_files
from test_access import access_workspace, actors, account, headers, project


def exercise(client, teacher, student, **changes):
    response = client.post('/api/practice/assignments', headers=headers(teacher), json={
        'title':'Phối hợp BIM nhà ở', 'instructions':'Đối chiếu mô hình và giải thích các điểm cần phối hợp.',
        'group_name':'Nhóm thực hành A', 'student_ids':[student['user']['id']],
        'criteria':[{'id':'model','title':'Minh chứng mô hình','max_points':6,'description':'Đối tượng, nguồn và hình học phù hợp.'},
                    {'id':'coordination','title':'Giải thích phối hợp','max_points':4,'description':'Nhận xét có căn cứ.'}], **changes,
    })
    assert response.status_code == 201, response.text
    return response.json()


def source_run(client, student):
    item = project(client, student)
    sources = []
    for file in demo_files()[:3]:
        response = client.post('/api/inspections',headers=headers(student),files={'file':(file['name'],file['content'].encode())},
                               data={'project_id':item['id'],'logical_source':file['name'],'revision':'R01'})
        assert response.status_code == 200,response.text
        sources.append(response.json())
    result = client.post('/api/inspections/clashes',headers=headers(student),json={'model_ids':[source['id'] for source in sources],'coordinates_confirmed':True})
    assert result.status_code == 200,result.text
    return item, sources, result.json()


def submit(client, student, task, item, run, identifier=None):
    response = client.post(f"/api/practice/assignments/{task['id']}/submissions",headers=headers(student),
                           json={'id':identifier or uuid4().hex,'project_id':item['id'],'run_id':run['id']})
    assert response.status_code in {200,201},response.text
    return response.json()


def test_assignment_submission_grade_and_private_evidence(access_workspace):
    client,database,directory = access_workspace
    admin,user,teacher,student = actors(client)
    outsider = account(client,'outsider')
    promoted = client.post(f"/api/admin/users/{outsider['user']['id']}/role",headers=headers(admin),json={'role':'student','expected_revision':outsider['user']['revision']})
    assert promoted.status_code == 200
    task = exercise(client,teacher,student)
    assert client.get('/api/practice/assignments',headers=headers(student)).json()['total'] == 1
    assert client.get('/api/practice/assignments',headers=headers(user)).status_code == 403
    assert client.post('/api/practice/assignments',headers=headers(student),json={}).status_code in {403,422}
    item,sources,run = source_run(client,student)
    record = submit(client,student,task,item,run)
    assert record['attempt'] == 1 and record['assignment']['criteria'][0]['max_points'] == 6
    assert record['grade'] is None
    base = f"/api/practice/submissions/{record['id']}"
    assert client.get(base,headers=headers(outsider)).status_code == 404
    assert client.get(base,headers=headers(admin)).status_code == 403
    assert client.get(f"/api/projects/{item['id']}",headers=headers(teacher)).status_code == 404
    evidence = client.get(base+'/evidence',headers=headers(teacher))
    assert evidence.status_code == 200,evidence.text
    assert {report['id'] for report in evidence.json()['reports']} == {source['id'] for source in sources}
    model_url = next(source['assets']['model'] for source in sources if source['assets'].get('model'))
    assert client.get(model_url,headers=headers(teacher)).status_code == 200
    assert client.get(model_url,headers=headers(outsider)).status_code == 404
    # A later upload belongs to the student's draft and must not become visible to the teacher.
    fresh=client.post('/api/inspections',headers=headers(student),files={'file':('draft.ifc',demo_files()[0]['content'].replace('SYNTHETIC GEOMETRY LAB','Draft only').encode())},
                      data={'project_id':item['id'],'logical_source':'draft.ifc'})
    assert fresh.status_code == 200,fresh.text
    assert client.get(fresh.json()['report_url'],headers=headers(teacher)).status_code == 404
    assert len(client.get(base+'/evidence',headers=headers(teacher)).json()['reports']) == 3
    assert client.delete(f"/api/projects/{item['id']}",headers=headers(student)).status_code == 409
    grade={'expected_revision':0,'published':False,'feedback':'Đối chiếu thêm ý đồ thiết kế.',
           'scores':[{'criterion_id':'model','points':5,'comment':'Cần bổ sung căn cứ.'},{'criterion_id':'coordination','points':3,'comment':'Giải thích thêm.'}]}
    denied=client.post(base+'/grade',headers=headers(student),json=grade)
    assert denied.status_code == 403
    saved=client.post(base+'/grade',headers=headers(teacher),json=grade)
    assert saved.status_code == 200,saved.text
    assert saved.json()['total_points'] == 8
    assert client.get(base,headers=headers(student)).json()['grade'] is None
    assert client.get('/api/practice/submissions?published=true',headers=headers(student)).json()['total'] == 0
    bad={**grade,'expected_revision':1,'scores':[{'criterion_id':'model','points':7,'comment':''},{'criterion_id':'coordination','points':3,'comment':''}]}
    assert client.post(base+'/grade',headers=headers(teacher),json=bad).status_code == 422
    published=client.post(base+'/grade',headers=headers(teacher),json={**grade,'expected_revision':1,'published':True})
    assert published.status_code == 200,published.text
    visible=client.get(base,headers=headers(student)).json()['grade']
    assert visible['published'] and visible['total_points'] == 8 and visible['reviewer_id'] == teacher['user']['id']
    assert client.post(base+'/grade',headers=headers(teacher),json={**grade,'expected_revision':2}).status_code == 409
    assert client.get(base,headers=headers(student)).json()['grade']['published'] is True
    assert client.post(base+'/grade',headers=headers(teacher),json=grade).status_code == 409
    same=submit(client,student,task,item,run,record['id'])
    assert same['id'] == record['id'] and same['attempt'] == 1
    later=submit(client,student,task,item,run)
    assert later['attempt'] == 2 and later['grade'] is None
    export=client.get(base+'/export',headers=headers(student))
    assert export.status_code == 200 and export.json()['grade']['total_points'] == 8
    assert database.project_issues.count_documents({'run_id':run['id'],'review.state':{'$ne':'unreviewed'}}) == 0


def test_admin_workspace_counts_and_sanitized_audit_are_private(access_workspace):
    client,database,_ = access_workspace
    admin,user,teacher,student = actors(client)
    private = project(client,student,'Private student evidence')
    database.auth_audit.insert_one({'actor_id':teacher['user']['id'],'action':'test_action','target':private['id'],'created_at':'2026-11-10T00:00:00+00:00','password':'must-not-leak'})
    for actor in [user,teacher,student]:
        assert client.get('/api/admin/overview',headers=headers(actor)).status_code == 403
        assert client.get('/api/admin/audit',headers=headers(actor)).status_code == 403
    overview = client.get('/api/admin/overview',headers=headers(admin))
    assert overview.status_code == 200,overview.text
    assert overview.json()['accounts']['teacher'] == 1 and overview.json()['accounts']['student'] == 1
    logs = client.get('/api/admin/audit?limit=100',headers=headers(admin))
    assert logs.status_code == 200 and logs.json()['total'] > 0
    assert 'must-not-leak' not in logs.text and 'Private student evidence' not in logs.text
    filtered=client.get('/api/admin/users?q=reviewer&role=teacher',headers=headers(admin))
    assert filtered.status_code == 200 and filtered.json()['total'] == 1
    assert filtered.json()['items'][0]['username'] == 'reviewer'


def test_practice_summary_and_source_download_preserve_scope(access_workspace):
    client,_,_ = access_workspace
    _,user,teacher,student = actors(client)
    assert client.get('/api/practice/summary').status_code == 401
    assert client.get('/api/practice/summary',headers=headers(user)).status_code == 403
    task=exercise(client,teacher,student)
    item,sources,run=source_run(client,student)
    record=submit(client,student,task,item,run)
    teacher_summary=client.get('/api/practice/summary',headers=headers(teacher))
    assert teacher_summary.status_code == 200,teacher_summary.text
    assert teacher_summary.json()['pending'] == 1 and teacher_summary.json()['assignments'] == 1
    url=f"/api/practice/submissions/{record['id']}/files/{sources[0]['id']}"
    source=client.get(url,headers=headers(teacher))
    assert source.status_code == 200 and source.content == demo_files()[0]['content'].encode()
    assert client.get(url,headers=headers(user)).status_code == 403
    assert client.get(f"/api/practice/submissions/{record['id']}/files/{uuid4().hex}",headers=headers(teacher)).status_code == 404


@pytest.mark.parametrize('revocation',['role','disabled','logout','password_change'])
def test_teacher_ai_is_advisory_and_revocation_prevents_saving(access_workspace,monkeypatch,revocation):
    from app.ai import AiService
    client,database,_=access_workspace
    _,_,teacher,student=actors(client)
    task=exercise(client,teacher,student)
    item,_,run=source_run(client,student)
    record=submit(client,student,task,item,run)
    url=f"/api/practice/submissions/{record['id']}/analysis"
    async def infer(self,request,messages,input_limit,output_limit):
        facts=json.loads(messages[1]['content'])
        return {'text':json.dumps({'assessment':facts['assessment'],'summary':'Cần đối chiếu hình học và ý đồ thiết kế trước khi đánh giá bài thực hành.',
                'priorities':[{'group_id':'g1','action':'verify_geometry','rationale':'Xác minh minh chứng và ý đồ thiết kế cho nhóm cấu kiện liên quan.'}],
                'next_steps':['review_design_intent'],'citations':['stats','g1'],'requires_review':True}),
                'metrics':{'input_tokens':759,'output_tokens':124,'elapsed_seconds':1.,'weights_verified':True}}
    monkeypatch.setattr(AiService,'infer',infer)
    assert client.post(url,headers=headers(student)).status_code == 403
    output=client.post(url,headers=headers(teacher))
    assert output.status_code == 200,output.text
    assert output.json()['model']['fine_tuned'] is False
    assert database.practice_submissions.find_one({'_id':record['id']})['grade'] is None
    assert 'analysis' not in client.get(f"/api/practice/submissions/{record['id']}",headers=headers(student)).json()
    async def revoked(*args,**kwargs):
        data=await infer(*args,**kwargs)
        if revocation == 'logout':
            response = await asyncio.to_thread(client.post,'/api/auth/logout',headers=headers(teacher))
            assert response.status_code == 200
        else:
            update = {'role':'user'} if revocation=='role' else {'disabled':True} if revocation=='disabled' else {'must_change_password':True}
            database.auth_users.update_one({'_id':teacher['user']['id']},{'$set':update})
        return data
    monkeypatch.setattr(AiService,'infer',revoked)
    assert client.post(url,headers=headers(teacher)).status_code in {401,403}
    assert database.practice_submissions.find_one({'_id':record['id']})['analysis']['created_at'] == output.json()['created_at']


def test_practice_json_limits_and_assignment_validation(access_workspace):
    client,_,_=access_workspace
    _,user,teacher,student=actors(client)
    payload={'title':'Long rubric','instructions':'\u611f'*10000,'student_ids':[student['user']['id']],
             'criteria':[{'id':f'item_{index}','title':'Criterion','max_points':1,'description':'\u611f'*1500} for index in range(20)]}
    assert len(json.dumps(payload,ensure_ascii=False).encode()) > 64*1024
    response=client.post('/api/practice/assignments',headers=headers(teacher),json=payload)
    assert response.status_code == 201,response.text
    oversized=client.post('/api/practice/assignments',headers={**headers(teacher),'Content-Type':'application/json'},
                          content=json.dumps({**payload,'instructions':'x'*(1024*1024)}))
    assert oversized.status_code == 413
    for changed in [{'student_ids':[user['user']['id']]}, {'student_ids':[student['user']['id']]*2},
                    {'criteria':[payload['criteria'][0]]*2}, {'due_at':'2026-11-10T08:00:00'},
                    {'criteria':[{**payload['criteria'][0],'max_points':1001}]}]:
        assert client.post('/api/practice/assignments',headers=headers(teacher),json={**payload,**changed}).status_code == 422


def test_late_submission_without_run_is_scoped_and_idempotent(access_workspace):
    client,database,_=access_workspace
    admin,user,teacher,student=actors(client)
    task=exercise(client,teacher,student,due_at='2020-01-01T07:00:00+07:00')
    assert task['due_at']=='2020-01-01T00:00:00+00:00'
    item,reports,_=source_run(client,student)
    base=f"/api/practice/assignments/{task['id']}/submissions"
    payload={'id':uuid4().hex,'project_id':item['id']}
    record=client.post(base,headers=headers(student),json=payload)
    assert record.status_code==201,record.text
    row=record.json()
    assert row['late'] is True and row['run_id'] is None and row['attempt']==1
    assert set(row['source_ids'])=={file['id'] for file in reports}
    assert client.post(base,headers=headers(student),json=payload).json()['id']==row['id']
    assert client.post(base,headers=headers(student),json={**payload,'project_id':str(uuid4())}).status_code==409
    empty=project(client,student,'Empty draft')
    assert client.post(base,headers=headers(student),json={'id':uuid4().hex,'project_id':empty['id']}).status_code==409
    foreign=project(client,user)
    assert client.post(base,headers=headers(student),json={'id':uuid4().hex,'project_id':foreign['id']}).status_code in {403,404}
    other=account(client,'second_teacher')
    assert client.post(f"/api/admin/users/{other['user']['id']}/role",headers=headers(admin),json={'role':'teacher','expected_revision':other['user']['revision']}).status_code==200
    assert client.get('/api/practice/submissions',headers=headers(other)).json()['total']==0
    for suffix in ['', '/evidence', '/export',f"/files/{reports[0]['id']}"]:
        assert client.get(f"/api/practice/submissions/{row['id']}"+suffix,headers=headers(other)).status_code==404
    assert client.get('/api/practice/students?q=second_teacher',headers=headers(teacher)).json()['total']==0
    assert 'students' not in client.get('/api/practice/assignments',headers=headers(student)).json()['items'][0]
    assert database.practice_submissions.count_documents({'student_id':student['user']['id']})==1
