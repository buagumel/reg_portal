from models import db, AcademicSession, RegistrationPeriod, AcademicHoliday, Semester


def list_sessions(programme_id=None):
    query = AcademicSession.query
    if programme_id is not None:
        query = query.filter(AcademicSession.programme_id == programme_id)
    return query.order_by(AcademicSession.start_date.desc().nullslast(), AcademicSession.id.desc()).all()


def get_session(session_id):
    return AcademicSession.query.get_or_404(session_id)


def create_session(name, start_date, end_date, programme_id=None):
    session_obj = AcademicSession(name=name, start_date=start_date, end_date=end_date, status='draft', programme_id=programme_id)
    db.session.add(session_obj)
    db.session.commit()
    return session_obj


def update_session(session_id, name, start_date, end_date, programme_id=None):
    session_obj = get_session(session_id)
    session_obj.name = name
    session_obj.start_date = start_date
    session_obj.end_date = end_date
    session_obj.programme_id = programme_id
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
    new_session = AcademicSession(name=new_name, start_date=new_start_date, end_date=new_end_date, status='draft', programme_id=source.programme_id)
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


def list_semesters():
    return Semester.query.order_by(Semester.order).all()


def list_semesters_for_programme(programme):
    """Filter Semester rows by the programme's calendar shape. Returns every
    Semester row if programme is None or has neither uses_semesters nor
    uses_terms set — the same 'show everything' behavior as an unscoped
    session has always had."""
    if programme is None:
        return list_semesters()
    types = []
    if programme.uses_semesters:
        types.append('semester')
    if programme.uses_terms:
        types.append('term')
    if not types:
        return list_semesters()
    return Semester.query.filter(Semester.period_type.in_(types)).order_by(Semester.order).all()


def list_periods(session_id):
    return RegistrationPeriod.query.filter_by(academic_session_id=session_id).order_by(RegistrationPeriod.id).all()


def get_period(period_id):
    return RegistrationPeriod.query.get_or_404(period_id)


def create_period(session_id, semester_id, opens_at, closes_at, min_credits, max_credits, registration_fee,
                   late_registration_ends_at=None, late_registration_fee=None,
                   exam_starts_at=None, exam_ends_at=None, result_release_at=None,
                   add_drop_opens_at=None, add_drop_closes_at=None):
    period = RegistrationPeriod(
        academic_session_id=session_id, semester_id=semester_id,
        opens_at=opens_at, closes_at=closes_at,
        min_credits=min_credits, max_credits=max_credits, registration_fee=registration_fee,
        late_registration_ends_at=late_registration_ends_at, late_registration_fee=late_registration_fee,
        exam_starts_at=exam_starts_at, exam_ends_at=exam_ends_at, result_release_at=result_release_at,
        add_drop_opens_at=add_drop_opens_at, add_drop_closes_at=add_drop_closes_at,
        is_active=False,
    )
    db.session.add(period)
    db.session.commit()
    return period


def update_period(period_id, **fields):
    period = get_period(period_id)
    for key, value in fields.items():
        setattr(period, key, value)
    db.session.commit()
    return period


def activate_period(period_id):
    """The single-active-session-and-semester enforcement point. Deactivates
    every other RegistrationPeriod, marks this period's session as current
    and 'open', and closes any other session that was previously current."""
    period = get_period(period_id)

    RegistrationPeriod.query.filter(RegistrationPeriod.id != period_id).update(
        {'is_active': False}, synchronize_session=False
    )
    period.is_active = True

    AcademicSession.query.filter(
        AcademicSession.id != period.academic_session_id,
        AcademicSession.is_current == True,
    ).update({'is_current': False, 'status': 'closed'}, synchronize_session=False)

    session_obj = get_session(period.academic_session_id)
    session_obj.is_current = True
    session_obj.status = 'open'

    db.session.commit()
    return period


def list_holidays(session_id):
    return AcademicHoliday.query.filter_by(academic_session_id=session_id).order_by(AcademicHoliday.starts_on).all()


def create_holiday(session_id, name, starts_on, ends_on):
    holiday = AcademicHoliday(academic_session_id=session_id, name=name, starts_on=starts_on, ends_on=ends_on)
    db.session.add(holiday)
    db.session.commit()
    return holiday


def list_inactive_periods():
    return RegistrationPeriod.query.filter_by(is_active=False).order_by(RegistrationPeriod.opens_at.desc()).all()
