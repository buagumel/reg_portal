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
    
class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)


class AcademicSession(db.Model):
    __tablename__ = 'academic_sessions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), unique=True, nullable=False)
    is_current = db.Column(db.Boolean, default=False, nullable=False)


class Semester(db.Model):
    __tablename__ = 'semesters'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    order = db.Column(db.Integer, nullable=False)


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

    academic_session = db.relationship('AcademicSession')
    semester = db.relationship('Semester')


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
    registered_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    updated_at = db.Column(db.DateTime, default=now_lagos, onupdate=now_lagos, nullable=False)

    __table_args__ = (db.UniqueConstraint('user_id', 'registration_period_id'),)

    registration_period = db.relationship('RegistrationPeriod')