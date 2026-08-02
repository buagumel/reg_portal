"""Interface for a future integration with the university's central
admission portal. Not implemented in this milestone — every admitted-student
import today goes through CSV upload (services/student_import.py) or manual
creation (services/admin_student.create_student). This module exists so a
real integration can be dropped in later without any calling code changing."""


def fetch_admitted_students(session_id):
    """Should return a list of admitted-student dicts (reg_no, name, email,
    department, programme, level, ...) fetched from the university's
    admission portal for the given academic session, in the same shape
    services/student_import.py's CSV rows use.

    TODO: implement the real HTTP integration once the admission portal's
    API contract is available. Until then this always raises, and the
    /admin/students/import/admission-portal route catches that by rendering
    a "not yet available" page rather than exposing a stack trace."""
    raise NotImplementedError('Admission portal integration is not implemented yet.')
