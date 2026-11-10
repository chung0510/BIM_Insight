from fastapi import Query, Request
from fastapi.responses import JSONResponse, FileResponse

from app.practice import AssignmentCreate, GradeCreate, SubmissionCreate, PracticeStore


def attach_practice_routes(app, projects, ai):
    practice = PracticeStore(projects,ai)
    from app.class_routes import attach_class_routes
    attach_class_routes(app,practice)

    @app.get('/api/practice/summary')
    def summary():
        return practice.summary()

    @app.get('/api/practice/students')
    def students(q: str = Query('',max_length=100), offset: int = Query(0,ge=0,le=100000), limit: int = Query(50,ge=1,le=200)):
        return practice.students(q,offset,limit)

    @app.get('/api/practice/assignments')
    def assignments(offset: int = Query(0,ge=0,le=100000), limit: int = Query(20,ge=1,le=100), class_id:str|None=None, unassigned:bool=False):
        return practice.assignments(offset,limit,class_id,unassigned)

    @app.post('/api/practice/assignments',status_code=201)
    def create_assignment(payload: AssignmentCreate):
        return practice.create_assignment(payload)

    @app.get('/api/practice/submissions')
    def submissions(assignment_id: str | None = None, offset: int = Query(0,ge=0,le=100000), limit: int = Query(20,ge=1,le=100), published: bool | None = None, class_id:str|None=None):
        return practice.submissions(offset,limit,assignment_id,published,class_id)

    @app.post('/api/practice/assignments/{assignment_id}/submissions',status_code=201)
    def submit(assignment_id: str, payload: SubmissionCreate):
        return practice.submit(assignment_id,payload)

    @app.get('/api/practice/submissions/{identifier}')
    def submission(identifier: str):
        return practice.public_submission(practice.require_submission(identifier))

    @app.get('/api/practice/submissions/{identifier}/evidence')
    def evidence(identifier: str):
        return practice.evidence(identifier)

    @app.get('/api/practice/submissions/{identifier}/files/{report_id}')
    def source_file(identifier: str, report_id: str):
        path, name = practice.source_file(identifier,report_id)
        return FileResponse(path,media_type='application/octet-stream',filename=name,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

    @app.post('/api/practice/submissions/{identifier}/grade')
    def grade(identifier: str, payload: GradeCreate):
        return practice.grade(identifier,payload)

    @app.post('/api/practice/submissions/{identifier}/analysis')
    async def analysis(identifier: str, request: Request):
        return await practice.analyze(request,identifier)

    @app.get('/api/practice/submissions/{identifier}/export')
    def export(identifier: str):
        record = practice.public_submission(practice.require_submission(identifier))
        return JSONResponse(record,headers={'Content-Disposition':f'attachment; filename="practice-{record["id"]}.json"','Cache-Control':'no-store'})
