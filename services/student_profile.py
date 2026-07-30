def get_profile_display(user):
    """Return derived, template-ready display strings for a student's
    programme/level/semester/session, with placeholders for unset fields."""
    programme = user.course or "Not set"

    if user.level and user.semester:
        level_semester = f"{user.level} · {user.semester}"
    elif user.semester:
        level_semester = user.semester
    elif user.level:
        level_semester = user.level
    else:
        level_semester = "Not set"

    session_display = user.session or "Not set"

    return {
        "programme": programme,
        "level_semester": level_semester,
        "session": session_display,
    }
