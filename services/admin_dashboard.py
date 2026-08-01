from models import (
    db, User, StudentRegistration, RegistrationPeriod, Payment, Course,
    RegisteredCourse, AdminAuditLog, AuditLog, Notification, AdminUser,
)


def get_dashboard_summary():
    active_period = RegistrationPeriod.query.filter_by(is_active=True).order_by(RegistrationPeriod.id.desc()).first()

    current_semester_registrations = 0
    active_courses = 0
    if active_period is not None:
        current_semester_registrations = StudentRegistration.query.filter_by(
            registration_period_id=active_period.id
        ).count()
        active_courses = Course.query.filter_by(
            academic_session_id=active_period.academic_session_id,
            semester_id=active_period.semester_id,
        ).count()

    total_students = User.query.count()
    active_students = User.query.filter_by(onboarding_completed=True).count()
    total_payments = Payment.query.filter_by(status='successful').count()
    departments = db.session.query(User.department).filter(User.department.isnot(None)).distinct().count()

    return {
        'total_students': total_students,
        'active_students': active_students,
        'current_semester_registrations': current_semester_registrations,
        'total_payments': total_payments,
        'active_courses': active_courses,
        'departments': departments,
    }


def get_activity_feed(limit=20):
    """Merge recent activity from several existing tables into one
    newest-first feed. No new event-logging system — this reads data
    that already exists for other reasons."""
    events = []

    for reg in StudentRegistration.query.order_by(StudentRegistration.registered_at.desc()).limit(limit).all():
        student = User.query.get(reg.user_id)
        events.append({
            'icon': 'fa-user-plus',
            'description': f'{student.name if student else "A student"} registered for {reg.registration_period.academic_session.name} {reg.registration_period.semester.name}',
            'timestamp': reg.registered_at,
        })

    for payment in Payment.query.filter_by(status='successful').order_by(Payment.verified_at.desc()).limit(limit).all():
        if payment.verified_at is None:
            continue
        events.append({
            'icon': 'fa-credit-card',
            'description': f'{payment.user.name} completed a payment of ₦{payment.total_amount:,.2f} (reference {payment.reference})',
            'timestamp': payment.verified_at,
        })

    for rc in RegisteredCourse.query.order_by(RegisteredCourse.added_at.desc()).limit(limit).all():
        student = User.query.get(rc.student_registration.user_id)
        events.append({
            'icon': 'fa-book-open',
            'description': f'{student.name if student else "A student"} registered for {rc.course.code} {rc.course.title}',
            'timestamp': rc.added_at,
        })

    for log in AdminAuditLog.query.filter_by(action='login').order_by(AdminAuditLog.created_at.desc()).limit(limit).all():
        admin_user = AdminUser.query.get(log.admin_user_id) if log.admin_user_id else None
        name = admin_user.name if admin_user else 'An administrator'
        events.append({
            'icon': 'fa-user-shield',
            'description': f'{name} logged into the admin portal',
            'timestamp': log.created_at,
        })

    for log in AuditLog.query.filter_by(action='profile_updated').order_by(AuditLog.created_at.desc()).limit(limit).all():
        user = User.query.get(log.user_id)
        name = user.name if user else 'A student'
        events.append({
            'icon': 'fa-id-card',
            'description': f'{name} updated their profile',
            'timestamp': log.created_at,
        })

    for note in Notification.query.filter_by(category='announcements').order_by(Notification.created_at.desc()).limit(limit).all():
        events.append({
            'icon': 'fa-bullhorn',
            'description': note.title,
            'timestamp': note.created_at,
        })

    events.sort(key=lambda e: e['timestamp'], reverse=True)
    return events[:limit]
