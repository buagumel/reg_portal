from models import db, AcademicSession, RegistrationPeriod


def list_sessions():
    return AcademicSession.query.order_by(AcademicSession.start_date.desc().nullslast(), AcademicSession.id.desc()).all()


def get_session(session_id):
    return AcademicSession.query.get_or_404(session_id)


def create_session(name, start_date, end_date):
    session_obj = AcademicSession(name=name, start_date=start_date, end_date=end_date, status='draft')
    db.session.add(session_obj)
    db.session.commit()
    return session_obj


def update_session(session_id, name, start_date, end_date):
    session_obj = get_session(session_id)
    session_obj.name = name
    session_obj.start_date = start_date
    session_obj.end_date = end_date
    db.session.commit()
    return session_obj


def archive_session(session_id):
    session_obj = get_session(session_id)
    if session_obj.is_current:
        return None, 'Cannot archive the currently active session. Activate a different session first.'
    session_obj.status = 'archived'
    db.session.commit()
    return session_obj, None


def clone_session(session_id, new_name, new_start_date, new_end_date):
    """Creates a new draft session and copies every RegistrationPeriod under
    the source session as a template (credit limits, fees, department
    overrides) — dates are never copied, since the whole point of cloning is
    reusing configuration for a *different* time window."""
    from models import DepartmentRegistrationRule

    source = get_session(session_id)
    new_session = AcademicSession(name=new_name, start_date=new_start_date, end_date=new_end_date, status='draft')
    db.session.add(new_session)
    db.session.flush()  # assigns new_session.id without committing yet

    for period in RegistrationPeriod.query.filter_by(academic_session_id=session_id).all():
        new_period = RegistrationPeriod(
            academic_session_id=new_session.id,
            semester_id=period.semester_id,
            opens_at=period.opens_at,
            closes_at=period.closes_at,
            min_credits=period.min_credits,
            max_credits=period.max_credits,
            registration_fee=period.registration_fee,
            late_registration_ends_at=period.late_registration_ends_at,
            late_registration_fee=period.late_registration_fee,
            exam_starts_at=period.exam_starts_at,
            exam_ends_at=period.exam_ends_at,
            result_release_at=period.result_release_at,
            is_active=False,
        )
        db.session.add(new_period)
        db.session.flush()

        for rule in DepartmentRegistrationRule.query.filter_by(registration_period_id=period.id).all():
            db.session.add(DepartmentRegistrationRule(
                registration_period_id=new_period.id,
                department=rule.department,
                min_credits=rule.min_credits,
                max_credits=rule.max_credits,
                registration_fee=rule.registration_fee,
            ))

    db.session.commit()
    return new_session
