from models import db, FeeStructure, AcademicSession


def list_fee_structures(session_id=None):
    query = FeeStructure.query
    if session_id is not None:
        query = query.filter(FeeStructure.academic_session_id == session_id)
    return query.join(AcademicSession).order_by(
        AcademicSession.start_date.desc().nullslast(), FeeStructure.category_id,
        FeeStructure.id,
    ).all()


def get_fee_structure(fee_structure_id):
    return FeeStructure.query.get_or_404(fee_structure_id)


def create_fee_structure(academic_session_id, semester_id, department_id, category_id, amount):
    row = FeeStructure(
        academic_session_id=academic_session_id, semester_id=semester_id,
        department_id=department_id, category_id=category_id, amount=amount,
    )
    db.session.add(row)
    db.session.commit()
    return row


def update_fee_structure(fee_structure_id, semester_id, department_id, category_id, amount):
    row = get_fee_structure(fee_structure_id)
    row.semester_id = semester_id
    row.department_id = department_id
    row.category_id = category_id
    row.amount = amount
    db.session.commit()
    return row


def delete_fee_structure(fee_structure_id):
    row = get_fee_structure(fee_structure_id)
    db.session.delete(row)
    db.session.commit()
