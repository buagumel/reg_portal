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