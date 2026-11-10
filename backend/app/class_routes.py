import asyncio

from fastapi import File, Query, UploadFile
from fastapi.responses import Response

from app.classes import ClassCreate, ClassChange, Revision, MembersChange, AssignmentClass
from app.class_roster import preview_roster
from app.provisioning import spreadsheet


def attach_class_routes(app, practice):
    classes=practice.classes

    @app.get('/api/practice/classes')
    def listing(archived:bool|None=False,q:str=Query('',max_length=100),offset:int=Query(0,ge=0,le=100000),limit:int=Query(20,ge=1,le=100)):
        return classes.listing(archived,q,offset,limit)

    @app.post('/api/practice/classes',status_code=201)
    def create(payload:ClassCreate):
        return classes.create(payload)

    @app.get('/api/practice/classes/{identifier}')
    def detail(identifier:str):
        return classes.detail(identifier)

    @app.post('/api/practice/classes/{identifier}')
    def update(identifier:str,payload:ClassChange):
        return classes.update(identifier,payload)

    @app.get('/api/practice/classes/{identifier}/members')
    def members(identifier:str,q:str=Query('',max_length=100),offset:int=Query(0,ge=0,le=100000),limit:int=Query(50,ge=1,le=200)):
        return classes.members(identifier,q,offset,limit)

    @app.post('/api/practice/classes/{identifier}/members')
    def add_members(identifier:str,payload:MembersChange):
        return classes.add_members(identifier,payload)

    @app.post('/api/practice/classes/{identifier}/members/{student_id}/remove')
    def remove(identifier:str,student_id:str,payload:Revision):
        return classes.remove_member(identifier,student_id,payload)

    @app.post('/api/practice/classes/{identifier}/members/preview')
    async def preview(identifier:str,file:UploadFile=File(...)):
        data=await file.read(2*1024*1024+1)
        return await asyncio.to_thread(preview_roster,classes,identifier,data,file.filename or '')

    @app.get('/api/practice/classes/{identifier}/members/template')
    def template(identifier:str):
        classes.require(identifier,True)
        return Response(spreadsheet(['Mã sinh viên','Lớp hành chính'],[['000123','22XD1']]),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="class-roster.xlsx"','Cache-Control':'no-store'})

    @app.post('/api/practice/assignments/{identifier}/class')
    def attach(identifier:str,payload:AssignmentClass):
        return classes.attach_assignment(identifier,payload)

    @app.get('/api/practice/classes/{identifier}/gradebook')
    def gradebook(identifier:str,assignment_id:str,offset:int=Query(0,ge=0,le=100000),limit:int=Query(50,ge=1,le=200)):
        return classes.gradebook(identifier,assignment_id,offset,limit)

    @app.get('/api/practice/classes/{identifier}/gradebook/export')
    def export(identifier:str,assignment_id:str):
        return Response(classes.export_gradebook(identifier,assignment_id),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="class-gradebook.xlsx"','Cache-Control':'no-store'})

    @app.get('/api/practice/notifications')
    def notifications(offset:int=Query(0,ge=0,le=100000),limit:int=Query(20,ge=1,le=100)):
        return classes.notifications(offset,limit)

    @app.post('/api/practice/notifications/{identifier}/read')
    def read(identifier:str):
        return classes.read_notification(identifier)
