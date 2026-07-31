"""Dev-only script: seeds demo students for manual testing of the
auth + onboarding flow. Safe to re-run; skips students that already exist.

Usage: python seed_dev_data.py
"""
from datetime import date, timedelta

from app import app
from models import (
    db, User, now_lagos,
    AcademicSession, Semester, RegistrationPeriod, DepartmentRegistrationRule, StudentRegistration, Course,
)

DEFAULT_PASSWORD = "Default@123"

DEMO_STUDENTS = [
    dict(
        reg_no="2308-2301-0001", name="Amina Yusuf", first_login=True, onboarding_completed=False,
        student_type="National", state="Jigawa", lga="Kazaure", nationality="Nigeria",
        dob=date(2002, 3, 14), gender="Female", semester="1st Semester", level="Year 1",
        session="2025/2026", department="Computer Science", course="ND Computer Science",
        email=None, phone=None, address=None,
    ),
    dict(
        reg_no="2308-2301-0002", name="Bello Ibrahim", first_login=False, onboarding_completed=False,
        student_type="National", state="Jigawa", lga="Kazaure", nationality="Nigeria",
        dob=date(2001, 11, 2), gender="Male", semester="1st Semester", level="Year 1",
        session="2025/2026", department="Computer Science", course="ND Computer Science",
        email=None, phone=None, address=None,
    ),
    dict(
        reg_no="2308-2301-0003", name="Chiamaka Okafor", first_login=False, onboarding_completed=True,
        email_verified=True,
        student_type="International", state="Anambra", lga="Awka South", nationality="Nigeria",
        dob=date(2000, 7, 22), gender="Female", semester="2nd Semester", level=None,
        session="2025/2026", department="Information Technology", course="International Diploma",
        email="chiamaka.demo@example.com", phone="08012345678", address="12 Unity Road, Kazaure",
    ),
    dict(
        reg_no="2308-2301-0004", name="David Adeyemi", first_login=False, onboarding_completed=True,
        email_verified=True,
        student_type="National", state="Oyo", lga="Ibadan North", nationality="Nigeria",
        dob=date(1999, 5, 9), gender="Male", semester="2nd Semester", level="Year 2",
        session="2025/2026", department="Information Technology", course="HND Information Technology",
        email="david.demo@example.com", phone="08087654321", address="4 Freedom Ave, Ibadan",
    ),
]


def seed():
    with app.app_context():
        db.create_all()
        created = 0
        for data in DEMO_STUDENTS:
            if User.query.filter_by(reg_no=data["reg_no"]).first():
                print(f"Skipping {data['reg_no']} (already exists)")
                continue
            user = User(**data)
            user.set_password(DEFAULT_PASSWORD)
            db.session.add(user)
            created += 1
            print(
                f"Created {data['reg_no']} ({data['name']}) — "
                f"first_login={data['first_login']}, onboarding_completed={data['onboarding_completed']}"
            )
        db.session.commit()
        seed_registration_config()
        seed_courses()
        print(f"\nDone. {created} student(s) created. Default password for first_login=True accounts: {DEFAULT_PASSWORD}")


def seed_registration_config():
    session_name = '2025/2026'
    academic_session = AcademicSession.query.filter_by(name=session_name).first()
    if not academic_session:
        academic_session = AcademicSession(name=session_name, is_current=True)
        db.session.add(academic_session)
        db.session.commit()
        print(f'Created academic session {session_name}')
    else:
        print(f'Skipping academic session {session_name} (already exists)')

    semesters = {}
    for name, order in [('First Semester', 1), ('Second Semester', 2)]:
        semester = Semester.query.filter_by(name=name).first()
        if not semester:
            semester = Semester(name=name, order=order)
            db.session.add(semester)
            db.session.commit()
            print(f'Created semester {name}')
        else:
            print(f'Skipping semester {name} (already exists)')
        semesters[name] = semester

    active_period = RegistrationPeriod.query.filter_by(
        academic_session_id=academic_session.id, semester_id=semesters['First Semester'].id
    ).first()
    if not active_period:
        active_period = RegistrationPeriod(
            academic_session_id=academic_session.id,
            semester_id=semesters['First Semester'].id,
            opens_at=now_lagos() - timedelta(days=3),
            closes_at=now_lagos() + timedelta(days=21),
            min_credits=15, max_credits=24, registration_fee=45000,
            is_active=True,
        )
        db.session.add(active_period)
        db.session.commit()
        print('Created active RegistrationPeriod: 2025/2026 First Semester (open)')
    else:
        print('Skipping active RegistrationPeriod (already exists)')

    upcoming_period = RegistrationPeriod.query.filter_by(
        academic_session_id=academic_session.id, semester_id=semesters['Second Semester'].id
    ).first()
    if not upcoming_period:
        upcoming_period = RegistrationPeriod(
            academic_session_id=academic_session.id,
            semester_id=semesters['Second Semester'].id,
            opens_at=now_lagos() + timedelta(days=90),
            closes_at=now_lagos() + timedelta(days=110),
            min_credits=15, max_credits=24, registration_fee=45000,
            is_active=False,
        )
        db.session.add(upcoming_period)
        db.session.commit()
        print('Created upcoming RegistrationPeriod: 2025/2026 Second Semester (not yet open)')
    else:
        print('Skipping upcoming RegistrationPeriod (already exists)')

    rule = DepartmentRegistrationRule.query.filter_by(
        registration_period_id=active_period.id, department='Information Technology'
    ).first()
    if not rule:
        rule = DepartmentRegistrationRule(
            registration_period_id=active_period.id,
            department='Information Technology',
            min_credits=12, max_credits=21, registration_fee=None,
        )
        db.session.add(rule)
        db.session.commit()
        print('Created DepartmentRegistrationRule for Information Technology')
    else:
        print('Skipping DepartmentRegistrationRule for Information Technology (already exists)')

    david = User.query.filter_by(reg_no='2308-2301-0004').first()
    if david:
        existing_reg = StudentRegistration.query.filter_by(
            user_id=david.id, registration_period_id=active_period.id
        ).first()
        if not existing_reg:
            demo_registration = StudentRegistration(
                user_id=david.id,
                registration_period_id=active_period.id,
                status='registered',
                payment_status='paid',
                payment_reference='SIMULATED-DEMO000001',
                credits_registered=0,
            )
            db.session.add(demo_registration)
            db.session.commit()
            print(f'Created demo StudentRegistration for {david.reg_no}')
        else:
            print(f'Skipping demo StudentRegistration for {david.reg_no} (already exists)')


def seed_courses():
    academic_session = AcademicSession.query.filter_by(name='2025/2026').first()
    first_semester = Semester.query.filter_by(name='First Semester').first()
    if not academic_session or not first_semester:
        print('Skipping course seed — run seed_registration_config first')
        return

    courses_data = [
        dict(code='CSC 310', title='Database Systems', credits=3, department='Computer Science',
             level='Year 1', course_type='core', instructor='Dr. A. Bello', schedule='Mon/Wed 10:00-11:30'),
        dict(code='MAT 202', title='Calculus II', credits=4, department='Computer Science',
             level='Year 1', course_type='core', instructor='Dr. F. Musa', schedule='Tue/Thu 08:00-09:30'),
        dict(code='CSC 212', title='Digital Logic', credits=3, department='Computer Science',
             level='Year 1', course_type='core', instructor=None, schedule=None),
        dict(code='GST 202', title='Entrepreneurship', credits=1, department='Computer Science',
             level=None, course_type='elective', instructor='Mrs. K. Eze', schedule='Fri 09:00-10:00'),
        dict(code='CSC 330', title='Artificial Intelligence', credits=3, department='Computer Science',
             level='Year 1', course_type='elective', instructor='Dr. A. Bello', schedule='Wed 13:00-15:00'),
        dict(code='ITC 301', title='Network Fundamentals', credits=3, department='Information Technology',
             level=None, course_type='core', instructor='Mr. S. Danjuma', schedule='Mon/Wed 12:00-13:30'),
        dict(code='ITC 315', title='Web Technologies', credits=3, department='Information Technology',
             level=None, course_type='elective', instructor='Mr. S. Danjuma', schedule='Thu 10:00-12:00'),
        dict(code='ITC 320', title='IT Systems Lab', credits=2, department='Information Technology',
             level=None, course_type='lab', instructor=None, schedule=None),
    ]

    created = 0
    for data in courses_data:
        existing = Course.query.filter_by(
            code=data['code'], academic_session_id=academic_session.id, semester_id=first_semester.id
        ).first()
        if existing:
            continue
        course = Course(
            academic_session_id=academic_session.id,
            semester_id=first_semester.id,
            description=f"{data['title']} — core curriculum course.",
            **data,
        )
        db.session.add(course)
        created += 1
    db.session.commit()
    print(f'Created {created} course(s).')


if __name__ == "__main__":
    seed()
