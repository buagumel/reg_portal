from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timezone
import random
import string
from extensions import mail
from zoneinfo import ZoneInfo
from werkzeug.security import generate_password_hash, check_password_hash
from functions import ordinal

db = SQLAlchemy()

LAGOS_TZ = ZoneInfo("Africa/Lagos")


def now_lagos():
    """Current time as a naive datetime representing Lagos local time.
    SQLite has no native timezone support, so every datetime column in this
    app stores naive values on this convention — never store a tz-aware
    datetime directly."""
    return datetime.now(LAGOS_TZ).replace(tzinfo=None)


class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(250), unique=True)
    reg_no = db.Column(db.String(250), unique=True)
    name = db.Column(db.String(250))
    password_hash = db.Column(db.String(256))
    phone = db.Column(db.String(20))
    student_type = db.Column(db.String(30)) # International / National
    state = db.Column(db.String(50))
    lga = db.Column(db.String(50))
    address = db.Column(db.String(150))
    nationality = db.Column(db.String(150))
    gender = db.Column(db.String(20))
    dob = db.Column(db.Date)
    email_verified = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False) # False = Student, True = Admin
    first_login = db.Column(db.Boolean, default=True, nullable=False, server_default='1')
    onboarding_completed = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    semester = db.Column(db.String(50))
    department = db.Column(db.String(150))
    course = db.Column(db.String(150))
    profile_picture = db.Column(db.String(300))
    level = db.Column(db.String(50))
    session = db.Column(db.String(20))
    emergency_contact = db.Column(db.String(150), nullable=True)
    blood_group = db.Column(db.String(5), nullable=True)
    updated_at = db.Column(db.DateTime, default=now_lagos, onupdate=now_lagos, nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programmes.id'), nullable=True)
    account_status = db.Column(db.String(20), nullable=False, default='active', server_default='active')
    created_at = db.Column(db.DateTime, nullable=True, default=now_lagos)
    last_login_at = db.Column(db.DateTime, nullable=True)
    onboarding_completed_at = db.Column(db.DateTime, nullable=True)


    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def formatted_phone(self):
        """Return phone number with spaces every 4 characters.
        Example: 'abcdefghi' → 'abcd efgh i'
        """
        if not self.phone:
            return ''
        # Remove any existing spaces (just in case)
        raw = self.phone.replace(' ', '')
        # Split into chunks of 4
        chunks = [raw[i:i+4] for i in range(0, len(raw), 4)]
        return ' '.join(chunks)
    
    @property
    def formatted_dob(self):
        if self.dob is None:
            return ''
        return f"{ordinal(self.dob.day)} {self.dob.strftime('%b')} {self.dob.year}"

    department_ref = db.relationship('Department', foreign_keys=[department_id])
    programme = db.relationship('Programme', foreign_keys=[programme_id])

class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reference = db.Column(db.String(50), unique=True, nullable=False)
    idempotency_key = db.Column(db.String(64), unique=True, nullable=False)
    rrr = db.Column(db.String(50), nullable=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('student_registrations.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    gateway_status = db.Column(db.String(100), nullable=True)
    initiated_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User')
    registration = db.relationship('StudentRegistration')


class AcademicSession(db.Model):
    __tablename__ = 'academic_sessions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), nullable=False)
    is_current = db.Column(db.Boolean, default=False, nullable=False)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='draft', server_default='draft')
    programme_id = db.Column(db.Integer, db.ForeignKey('programmes.id'), nullable=True)

    __table_args__ = (db.UniqueConstraint('name', 'programme_id', name='uq_academic_sessions_name_programme_id'),)

    programme = db.relationship('Programme')


class Semester(db.Model):
    __tablename__ = 'semesters'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    order = db.Column(db.Integer, nullable=False)
    period_type = db.Column(db.String(20), nullable=False, default='semester', server_default='semester')


class RegistrationPeriod(db.Model):
    __tablename__ = 'registration_periods'
    id = db.Column(db.Integer, primary_key=True)
    academic_session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    semester_id = db.Column(db.Integer, db.ForeignKey('semesters.id'), nullable=False)
    opens_at = db.Column(db.DateTime, nullable=False)
    closes_at = db.Column(db.DateTime, nullable=False)
    min_credits = db.Column(db.Integer, nullable=False)
    max_credits = db.Column(db.Integer, nullable=False)
    registration_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    late_registration_ends_at = db.Column(db.DateTime, nullable=True)
    late_registration_fee = db.Column(db.Numeric(10, 2), nullable=True)
    exam_starts_at = db.Column(db.DateTime, nullable=True)
    exam_ends_at = db.Column(db.DateTime, nullable=True)
    result_release_at = db.Column(db.DateTime, nullable=True)
    add_drop_opens_at = db.Column(db.DateTime, nullable=True)
    add_drop_closes_at = db.Column(db.DateTime, nullable=True)

    academic_session = db.relationship('AcademicSession')
    semester = db.relationship('Semester')

    @property
    def programme(self):
        return self.academic_session.programme if self.academic_session else None


class DepartmentRegistrationRule(db.Model):
    __tablename__ = 'department_registration_rules'
    id = db.Column(db.Integer, primary_key=True)
    registration_period_id = db.Column(db.Integer, db.ForeignKey('registration_periods.id'), nullable=False)
    department = db.Column(db.String(150), nullable=False)
    min_credits = db.Column(db.Integer, nullable=True)
    max_credits = db.Column(db.Integer, nullable=True)
    registration_fee = db.Column(db.Numeric(10, 2), nullable=True)

    __table_args__ = (db.UniqueConstraint('registration_period_id', 'department'),)


class StudentRegistration(db.Model):
    __tablename__ = 'student_registrations'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    registration_period_id = db.Column(db.Integer, db.ForeignKey('registration_periods.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='registered')
    payment_status = db.Column(db.String(20), nullable=False, default='pending')
    payment_reference = db.Column(db.String(100), nullable=True)
    credits_registered = db.Column(db.Integer, nullable=False, default=0)
    courses_submitted = db.Column(db.Boolean, default=False, nullable=False)
    registered_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    updated_at = db.Column(db.DateTime, default=now_lagos, onupdate=now_lagos, nullable=False)
    is_locked = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    deadline_override = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint('user_id', 'registration_period_id'),)

    registration_period = db.relationship('RegistrationPeriod')


class Course(db.Model):
    __tablename__ = 'courses'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    credits = db.Column(db.Integer, nullable=False)
    course_type = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active', server_default='active')
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)


class CourseOffering(db.Model):
    __tablename__ = 'course_offerings'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    credits = db.Column(db.Integer, nullable=False)
    department = db.Column(db.String(150), nullable=False)
    level = db.Column(db.String(50), nullable=True)
    course_type = db.Column(db.String(20), nullable=False)
    academic_session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    semester_id = db.Column(db.Integer, db.ForeignKey('semesters.id'), nullable=False)
    description = db.Column(db.Text, nullable=True)
    instructor = db.Column(db.String(150), nullable=True)
    schedule = db.Column(db.String(200), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active', server_default='active')
    max_capacity = db.Column(db.Integer, nullable=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)

    __table_args__ = (db.UniqueConstraint('code', 'academic_session_id', 'semester_id'),)

    academic_session = db.relationship('AcademicSession')
    semester = db.relationship('Semester')
    department_ref = db.relationship('Department', foreign_keys=[department_id])
    course = db.relationship('Course', backref='offerings')

    @property
    def programme(self):
        return self.academic_session.programme if self.academic_session else None


class RegisteredCourse(db.Model):
    __tablename__ = 'registered_courses'
    id = db.Column(db.Integer, primary_key=True)
    student_registration_id = db.Column(db.Integer, db.ForeignKey('student_registrations.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course_offerings.id'), nullable=False)
    grade = db.Column(db.String(5), nullable=True)
    added_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

    __table_args__ = (db.UniqueConstraint('student_registration_id', 'course_id'),)

    course = db.relationship('CourseOffering')
    student_registration = db.relationship('StudentRegistration', backref='registered_courses')


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(20), nullable=False)
    priority = db.Column(db.String(10), nullable=False, default='medium')
    related_url = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)


class PaymentCategory(db.Model):
    __tablename__ = 'payment_categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    code = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    default_amount = db.Column(db.Numeric(10, 2), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)


class PaymentItem(db.Model):
    __tablename__ = 'payment_items'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('payment_categories.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)

    payment = db.relationship('Payment', backref='items')
    category = db.relationship('PaymentCategory')


class PaymentReceipt(db.Model):
    __tablename__ = 'payment_receipts'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), unique=True, nullable=False)
    receipt_number = db.Column(db.String(50), unique=True, nullable=False)
    generated_at = db.Column(db.DateTime, default=now_lagos, nullable=False)


class GatewayResponse(db.Model):
    __tablename__ = 'gateway_responses'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False)
    raw_payload = db.Column(db.Text, nullable=False)
    received_at = db.Column(db.DateTime, default=now_lagos, nullable=False)


class Permission(db.Model):
    __tablename__ = 'permissions'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)


class AdminRole(db.Model):
    __tablename__ = 'admin_roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)

    permissions = db.relationship('Permission', secondary='role_permissions', backref='roles')


class RolePermission(db.Model):
    __tablename__ = 'role_permissions'
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('admin_roles.id'), nullable=False)
    permission_id = db.Column(db.Integer, db.ForeignKey('permissions.id'), nullable=False)

    __table_args__ = (db.UniqueConstraint('role_id', 'permission_id'),)


class AdminUser(db.Model, UserMixin):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(250), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(250), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('admin_roles.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    first_login = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(45), nullable=True)

    role = db.relationship('AdminRole')

    def get_id(self):
        return f'admin:{self.id}'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class AdminAuditLog(db.Model):
    __tablename__ = 'admin_audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    target_type = db.Column(db.String(50), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)


class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    faculty = db.Column(db.String(150), nullable=True)
    head_name = db.Column(db.String(150), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)


class Programme(db.Model):
    __tablename__ = 'programmes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    program_type = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    uses_semesters = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    uses_terms = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    duration = db.Column(db.String(50), nullable=True)


class ProgrammeDepartment(db.Model):
    __tablename__ = 'programme_departments'
    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programmes.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

    __table_args__ = (db.UniqueConstraint('programme_id', 'department_id'),)

    programme = db.relationship('Programme', backref='programme_departments')
    department = db.relationship('Department', backref='programme_departments')


class CoursePrerequisite(db.Model):
    __tablename__ = 'course_prerequisites'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    prerequisite_course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)

    __table_args__ = (db.UniqueConstraint('course_id', 'prerequisite_course_id'),)

    course = db.relationship('Course', foreign_keys=[course_id])
    prerequisite_course = db.relationship('Course', foreign_keys=[prerequisite_course_id])


class CourseCorequisite(db.Model):
    __tablename__ = 'course_corequisites'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    corequisite_course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)

    __table_args__ = (db.UniqueConstraint('course_id', 'corequisite_course_id'),)

    course = db.relationship('Course', foreign_keys=[course_id])
    corequisite_course = db.relationship('Course', foreign_keys=[corequisite_course_id])


class CourseAssessmentComponent(db.Model):
    __tablename__ = 'course_assessment_components'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course_offerings.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    weight_percent = db.Column(db.Integer, nullable=False)

    course = db.relationship('CourseOffering', backref='assessment_components')


class AcademicHoliday(db.Model):
    __tablename__ = 'academic_holidays'
    id = db.Column(db.Integer, primary_key=True)
    academic_session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    starts_on = db.Column(db.Date, nullable=False)
    ends_on = db.Column(db.Date, nullable=False)

    academic_session = db.relationship('AcademicSession', backref='holidays')


class StudentImportJob(db.Model):
    __tablename__ = 'student_import_jobs'
    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='processing')
    created_count = db.Column(db.Integer, nullable=False, default=0)
    updated_count = db.Column(db.Integer, nullable=False, default=0)
    skipped_count = db.Column(db.Integer, nullable=False, default=0)
    duplicate_count = db.Column(db.Integer, nullable=False, default=0)
    error_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)


class StudentImportError(db.Model):
    __tablename__ = 'student_import_errors'
    id = db.Column(db.Integer, primary_key=True)
    import_job_id = db.Column(db.Integer, db.ForeignKey('student_import_jobs.id'), nullable=False)
    row_number = db.Column(db.Integer, nullable=False)
    raw_row = db.Column(db.Text, nullable=False)
    reason = db.Column(db.String(300), nullable=False)

    import_job = db.relationship('StudentImportJob', backref='errors')


class CourseImportJob(db.Model):
    __tablename__ = 'course_import_jobs'
    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='processing')
    created_count = db.Column(db.Integer, nullable=False, default=0)
    updated_count = db.Column(db.Integer, nullable=False, default=0)
    skipped_count = db.Column(db.Integer, nullable=False, default=0)
    duplicate_count = db.Column(db.Integer, nullable=False, default=0)
    error_count = db.Column(db.Integer, nullable=False, default=0)
    mismatched_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)


class CourseImportError(db.Model):
    __tablename__ = 'course_import_errors'
    id = db.Column(db.Integer, primary_key=True)
    import_job_id = db.Column(db.Integer, db.ForeignKey('course_import_jobs.id'), nullable=False)
    row_number = db.Column(db.Integer, nullable=False)
    raw_row = db.Column(db.Text, nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    severity = db.Column(db.String(10), nullable=False, default='error', server_default='error')

    import_job = db.relationship('CourseImportJob', backref='errors')


class RegistrationOverride(db.Model):
    __tablename__ = 'registration_overrides'
    id = db.Column(db.Integer, primary_key=True)
    student_registration_id = db.Column(db.Integer, db.ForeignKey('student_registrations.id'), nullable=False)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

    student_registration = db.relationship('StudentRegistration', backref='overrides')
    admin_user = db.relationship('AdminUser')
