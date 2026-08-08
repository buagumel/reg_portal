import csv
import io

from flask import Response
from openpyxl import Workbook

from models import User, StudentRegistration, CourseOffering, Department, Payment

VALID_DATA_TYPES = ('students', 'registrations', 'courses', 'departments', 'payments')


def _rows_for(data_type, student_ids=None):
    """Returns (headers, rows) for one of VALID_DATA_TYPES, or (None, None)
    if data_type is unrecognized. rows is a list of lists, already
    stringified — safe to write directly to CSV or Excel. student_ids, if
    given, only ever filters the 'students' export (used by the Student
    Directory's bulk "Export Selected" action)."""
    if data_type == 'students':
        query = User.query
        if student_ids:
            query = query.filter(User.id.in_(student_ids))
        headers = ['reg_no', 'name', 'email', 'department', 'programme', 'level', 'semester', 'status']
        rows = [
            [u.reg_no, u.name, u.email or '', u.department or '', u.course or '', u.level or '', u.semester or '', u.account_status]
            for u in query.order_by(User.reg_no).all()
        ]
    elif data_type == 'registrations':
        headers = ['reg_no', 'session', 'semester', 'status', 'payment_status', 'credits_registered', 'registered_at']
        rows = [
            [
                User.query.get(sr.user_id).reg_no,
                sr.registration_period.academic_session.name, sr.registration_period.semester.name,
                sr.status, sr.payment_status, sr.credits_registered, sr.registered_at.strftime('%Y-%m-%d %H:%M'),
            ]
            for sr in StudentRegistration.query.order_by(StudentRegistration.registered_at.desc()).all()
        ]
    elif data_type == 'courses':
        headers = ['code', 'title', 'department', 'level', 'semester', 'credits', 'status']
        rows = [
            [c.code, c.title, c.department, c.level or '', c.semester.name, c.credits, c.status]
            for c in CourseOffering.query.order_by(CourseOffering.code).all()
        ]
    elif data_type == 'departments':
        headers = ['name', 'code', 'faculty', 'status']
        rows = [[d.name, d.code, d.faculty or '', d.status] for d in Department.query.order_by(Department.name).all()]
    elif data_type == 'payments':
        headers = ['reference', 'reg_no', 'amount', 'status', 'initiated_at']
        rows = [
            [p.reference, p.user.reg_no, str(p.total_amount), p.status, p.initiated_at.strftime('%Y-%m-%d %H:%M')]
            for p in Payment.query.order_by(Payment.initiated_at.desc()).all()
        ]
    else:
        return None, None
    return headers, rows


def export_csv(data_type, student_ids=None):
    headers, rows = _rows_for(data_type, student_ids)
    if headers is None:
        return None
    output = io.StringIO()
    output.write('﻿')  # UTF-8 BOM so Excel on Windows reads non-ASCII characters correctly
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={data_type}.csv'},
    )


def export_excel(data_type, student_ids=None):
    headers, rows = _rows_for(data_type, student_ids)
    if headers is None:
        return None
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = data_type.capitalize()
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return Response(
        output.getvalue(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename={data_type}.xlsx'},
    )
