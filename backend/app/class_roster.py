from io import BytesIO
from zipfile import ZipFile

from fastapi import HTTPException
from openpyxl import load_workbook

from app.provisioning import cell_text, header_key


def preview_roster(classes, identifier, data, filename):
    classes.require(identifier,True)
    if not filename.lower().endswith('.xlsx') or not data or len(data)>2*1024*1024:
        raise HTTPException(422,'excel_file_invalid')
    workbook=None
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries=archive.infolist()
            if len(entries)>2000 or sum(item.file_size for item in entries)>20*1024*1024 or any(item.flag_bits&1 or 'vbaProject' in item.filename or 'externalLinks/' in item.filename for item in entries):
                raise ValueError
        workbook=load_workbook(BytesIO(data),read_only=True,data_only=False,keep_links=False)
        if len(workbook.worksheets)!=1:
            raise HTTPException(422,'excel_one_sheet_required')
        sheet=workbook.active
        if (sheet.max_row or 0)>201 or (sheet.max_column or 0)>20:
            raise HTTPException(422,'excel_scope_limit')
        raw=list(sheet.iter_rows(max_row=202,max_col=21))
        values=[[cell_text(cell).strip() for cell in row] for row in raw]
        while values and not any(values[-1]): values.pop()
        if len(values)<2 or len(values)>201:
            raise HTTPException(422,'excel_scope_limit')
        width=len(values[0])
        while width and not values[0][width-1]: width-=1
        keys=[header_key(value) for value in values[0][:width]]
        if len(set(keys))!=width or not 1<=width<=20 or any(any(row[width:]) for row in values):
            raise HTTPException(422,'excel_columns_invalid')
        code=next((i for i,key in enumerate(keys) if key in {'masinhvien','mssv','masv','studentid'}),None)
        cohort=next((i for i,key in enumerate(keys) if key in {'lophanhchinh','lop','administrativeclass'}),None)
        if code is None:
            raise HTTPException(422,'class_excel_headers')
        rows,errors,seen,seen_students=[],[],set(),set()
        for number,line in enumerate(values[1:],2):
            if not any(line): continue
            identity=line[code].casefold(); original=raw[number-1][code].value
            if isinstance(original,bool) or isinstance(original,(int,float)) and (not float(original).is_integer() or abs(original)>=10**15):
                errors.append({'row':number,'code':'excel_code_as_text_required','value':line[code]}); continue
            if not identity or len(identity)>100 or identity in seen:
                errors.append({'row':number,'code':'class_excel_duplicate','value':line[code]}); continue
            seen.add(identity)
            matches=list(classes.db.auth_users.find({'role':'student','disabled':False,'$or':[{'identity_code':identity},{'username':identity}]},{'display_name':1,'username':1,'identity_code':1}).limit(2))
            if len(matches)!=1:
                errors.append({'row':number,'code':'class_excel_account_missing','value':line[code]}); continue
            administrative_class=line[cohort] if cohort is not None else ''
            if len(administrative_class)>100:
                errors.append({'row':number,'code':'class_excel_cohort_invalid','value':line[code]}); continue
            user=matches[0]
            if user['_id'] in seen_students:
                errors.append({'row':number,'code':'class_excel_duplicate','value':line[code]}); continue
            seen_students.add(user['_id'])
            rows.append({'student_id':user['_id'],'code':user.get('identity_code') or user['username'],'display_name':user['display_name'],
                         'administrative_class':administrative_class,'already_member':classes.is_member(identifier,user['_id'])})
        return {'rows':rows,'errors':errors,'valid_count':len(rows)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422,'excel_file_invalid') from None
    finally:
        if workbook is not None: workbook.close()
