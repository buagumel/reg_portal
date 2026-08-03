"""Dev-only script: seeds demo students for manual testing of the
auth + onboarding flow. Safe to re-run; skips students that already exist.

Usage: python seed_dev_data.py
"""
from datetime import date, timedelta

from app import app
from models import (
    db, User, now_lagos,
    AcademicSession, Semester, RegistrationPeriod, DepartmentRegistrationRule, StudentRegistration, Course,
    Notification, PaymentCategory, Payment,
    AdminRole, Permission, AdminUser, Programme,
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
        seed_notifications()
        seed_profile_extras()
        seed_payment_categories()
        seed_payments()
        seed_admin_rbac()
        seed_admin_users()
        seed_programmes()
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
        dict(code='GST 101', title='Communication Skills', credits=2, department='Computer Science',
             level=None, course_type='core', instructor='Mrs. K. Eze', schedule='Mon 08:00-09:00'),
        dict(code='ITC 250', title='Software Engineering Principles', credits=5, department='Information Technology',
             level=None, course_type='core', instructor='Mr. S. Danjuma', schedule='Tue 14:00-16:00'),
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


def seed_notifications():
    chiamaka = User.query.filter_by(reg_no='2308-2301-0003').first()
    if not chiamaka:
        print('Skipping notification seed — run student seeding first')
        return

    existing_count = Notification.query.filter_by(user_id=chiamaka.id).count()
    if existing_count > 0:
        print(f'Skipping notification seed for {chiamaka.reg_no} (already has {existing_count})')
        return

    from services.notification import create_notification

    n1 = create_notification(
        chiamaka, 'Welcome to the Student Portal', 'Your profile setup is complete. Welcome aboard!',
        category='profile', priority='medium',
    )
    n2 = create_notification(
        chiamaka, 'Second semester exam timetable released',
        'Official examination timetable for the second semester is now available.',
        category='academic', priority='medium', related_url='/announcements',
    )
    n2.read_at = now_lagos()

    n3 = create_notification(
        chiamaka, 'System maintenance scheduled', 'The portal will be briefly unavailable for maintenance this weekend.',
        category='system', priority='low',
    )
    n4 = create_notification(
        chiamaka, 'Library extended hours during exams',
        'Main library extended hours (7:00 AM - 11:00 PM) starting during examination weeks.',
        category='announcements', priority='low',
    )
    n4.read_at = now_lagos()

    n5 = create_notification(
        chiamaka, 'Departmental seminar reminder', 'A departmental seminar takes place this week — attendance is optional.',
        category='academic', priority='low',
    )
    n5.read_at = now_lagos()
    n5.archived_at = now_lagos()

    db.session.commit()
    print(f'Created 5 demo notifications for {chiamaka.reg_no} (2 unread, 2 read, 1 archived)')


def seed_profile_extras():
    david = User.query.filter_by(reg_no='2308-2301-0004').first()
    if david and not david.emergency_contact:
        david.emergency_contact = 'Mrs. Adeyemi Adeyemi - 08033445566'
        david.blood_group = 'O+'
        db.session.commit()
        print(f'Set emergency contact/blood group for {david.reg_no}')
    else:
        print('Skipping profile extras seed (already set or David not found)')


def seed_payment_categories():
    categories = [
        ('Registration Fee', 'registration_fee', 'Per-semester registration fee (amount set by the active registration period).', None),
        ('Library Fee', 'library_fee', 'Annual library access and book borrowing fee.', 5000),
        ('Laboratory Fee', 'laboratory_fee', 'Per-semester laboratory materials and equipment fee.', 12000),
        ('Acceptance Fee', 'acceptance_fee', 'One-time fee paid on admission.', 50000),
        ('Hostel Fee', 'hostel_fee', 'Per-session hostel accommodation fee.', 45000),
        ('Transcript Fee', 'transcript_fee', 'Official transcript request and processing fee.', 7500),
        ('ID Card', 'id_card', 'Student ID card issuance or replacement.', 2000),
        ('Late Registration', 'late_registration', 'Penalty fee for registering after the deadline.', 10000),
    ]
    for name, code, description, default_amount in categories:
        if PaymentCategory.query.filter_by(code=code).first():
            print(f'Skipping payment category "{name}" (already exists)')
            continue
        db.session.add(PaymentCategory(
            name=name, code=code, description=description,
            default_amount=default_amount, is_active=True,
        ))
        db.session.commit()
        print(f'Seeded payment category: {name}')


def seed_payments():
    from services.payment import create_payment, initiate_payment, verify_payment, cancel_payment
    from services.payment_gateway import SimulatedGateway

    chiamaka = User.query.filter_by(reg_no='2308-2301-0003').first()
    if not chiamaka:
        print('Skipping seed_payments (Chiamaka demo user not found)')
        return

    if Payment.query.filter_by(user_id=chiamaka.id).count() > 0:
        print('Skipping seed_payments (Chiamaka already has payment history)')
        return

    library = PaymentCategory.query.filter_by(code='library_fee').first()
    id_card = PaymentCategory.query.filter_by(code='id_card').first()
    hostel = PaymentCategory.query.filter_by(code='hostel_fee').first()
    if not (library and id_card and hostel):
        print('Skipping seed_payments (categories not seeded yet)')
        return

    gateway = SimulatedGateway()

    # initiate_payment() calls url_for(..., _external=True), which needs an
    # active request context (no SERVER_NAME is configured on this app) —
    # matching this repo's established manual-verification pattern of
    # wrapping such calls in app.test_request_context().
    with app.test_request_context():
        # One successful payment, fully driven through the real service flow.
        p1 = create_payment(chiamaka, [(library, 1, library.default_amount)], idempotency_key='seed-payment-1')
        initiate_payment(gateway, p1, chiamaka)
        p1.gateway_status = 'successful'
        verify_payment(gateway, p1)

        # One cancelled payment. Created and cancelled *before* the pending
        # one below — validate_no_duplicate_pending only allows one pending
        # independent payment per user at a time, so p3 must be resolved
        # (cancelled) before p2 is created and left pending.
        p3 = create_payment(chiamaka, [(hostel, 1, hostel.default_amount)], idempotency_key='seed-payment-3')
        initiate_payment(gateway, p3, chiamaka)
        cancel_payment(p3)

        # One pending payment (RRR obtained, never completed — exercises Resume).
        p2 = create_payment(chiamaka, [(id_card, 1, id_card.default_amount)], idempotency_key='seed-payment-2')
        initiate_payment(gateway, p2, chiamaka)

    print('Seeded 3 demo payments for Chiamaka (1 successful, 1 pending, 1 cancelled)')


def seed_admin_rbac():
    permissions = [
        ('dashboard.view', 'View the admin dashboard'),
        ('sessions.manage', 'Create and manage academic sessions'),
        ('students.manage', 'Bulk-import and manage student accounts'),
        ('courses.manage', 'Manage the course catalog'),
        ('registration.manage', 'Open/close registration periods'),
        ('announcements.manage', 'Create system announcements'),
        ('reports.view', 'View and generate reports'),
        ('departments.manage', 'Create, edit, and manage departments'),
        ('onboarding.override', 'Manually mark a student\'s onboarding as complete, bypassing the onboarding wizard'),
    ]
    perm_objs = {}
    for code, description in permissions:
        perm = Permission.query.filter_by(code=code).first()
        if not perm:
            perm = Permission(code=code, description=description)
            db.session.add(perm)
            db.session.commit()
            print(f'Seeded permission: {code}')
        else:
            print(f'Skipping permission {code} (already exists)')
        perm_objs[code] = perm

    roles = {
        'Super Administrator': (
            'Complete system access',
            ['dashboard.view', 'sessions.manage', 'students.manage', 'courses.manage', 'registration.manage', 'announcements.manage', 'reports.view', 'departments.manage', 'onboarding.override'],
        ),
        'Academic Administrator': (
            'Course management, registration oversight, and announcements',
            ['dashboard.view', 'courses.manage', 'registration.manage', 'announcements.manage', 'departments.manage'],
        ),
    }
    for name, (description, codes) in roles.items():
        role = AdminRole.query.filter_by(name=name).first()
        if not role:
            role = AdminRole(name=name, description=description)
            db.session.add(role)
            db.session.commit()
            print(f'Seeded admin role: {name}')
        else:
            print(f'Skipping admin role {name} (already exists)')

        for code in codes:
            if perm_objs[code] not in role.permissions:
                role.permissions.append(perm_objs[code])
        db.session.commit()


def seed_programmes():
    programmes = [
        ('Certificate in Foundation Skills', 'CIFS', 'international', 'One-term foundational program for new students.'),
        ('International Diploma', 'INTLDIP', 'international', 'First or Second Semester.'),
        ('Advanced Diploma', 'ADVDIP', 'international', 'First or Second Semester.'),
        ('National Diploma', 'ND', 'nd', 'Annual rotation — ND1 and ND2, First and Second Semester.'),
        ('Higher National Diploma', 'HND', 'hnd', 'Annual rotation — HND1 and HND2, First and Second Semester.'),
    ]
    for name, code, program_type, description in programmes:
        if Programme.query.filter_by(code=code).first():
            print(f'Skipping programme {code} (already exists)')
            continue
        db.session.add(Programme(name=name, code=code, program_type=program_type, description=description))
        db.session.commit()
        print(f'Seeded programme: {name} ({code})')


def seed_admin_users():
    super_role = AdminRole.query.filter_by(name='Super Administrator').first()
    academic_role = AdminRole.query.filter_by(name='Academic Administrator').first()
    if not super_role or not academic_role:
        print('Skipping seed_admin_users (admin roles not seeded yet)')
        return

    admins = [
        ('super.admin@jspict.edu.ng', 'Amina Super-Admin', super_role.id),
        ('academic.admin@jspict.edu.ng', 'Bello Academic-Admin', academic_role.id),
    ]
    for email, name, role_id in admins:
        if AdminUser.query.filter_by(email=email).first():
            print(f'Skipping admin user {email} (already exists)')
            continue
        admin = AdminUser(email=email, name=name, role_id=role_id, is_active=True, first_login=True)
        admin.set_password(DEFAULT_PASSWORD)
        db.session.add(admin)
        db.session.commit()
        print(f'Seeded admin user: {email} ({name})')

    print(f'Default password for seeded admin accounts: {DEFAULT_PASSWORD}')


if __name__ == "__main__":
    seed()
