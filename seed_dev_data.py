"""Dev-only script: seeds demo students for manual testing of the
auth + onboarding flow. Safe to re-run; skips students that already exist.

Usage: python seed_dev_data.py
"""
from datetime import date

from app import app
from models import db, User

DEFAULT_PASSWORD = "Default@123"

DEMO_STUDENTS = [
    dict(
        reg_no="2308-2301-0001", name="Amina Yusuf", first_login=True, onboarding_completed=False,
        student_type="National", state="Jigawa", lga="Kazaure", nationality="Nigeria",
        dob=date(2002, 3, 14), gender="Female", semester="1st Semester",
        department="Computer Science", course="ND Computer Science",
        email=None, phone=None, address=None,
    ),
    dict(
        reg_no="2308-2301-0002", name="Bello Ibrahim", first_login=False, onboarding_completed=False,
        student_type="National", state="Jigawa", lga="Kazaure", nationality="Nigeria",
        dob=date(2001, 11, 2), gender="Male", semester="1st Semester",
        department="Computer Science", course="ND Computer Science",
        email=None, phone=None, address=None,
    ),
    dict(
        reg_no="2308-2301-0003", name="Chiamaka Okafor", first_login=False, onboarding_completed=True,
        email_verified=True,
        student_type="International", state="Anambra", lga="Awka South", nationality="Nigeria",
        dob=date(2000, 7, 22), gender="Female", semester="2nd Semester",
        department="Information Technology", course="International Diploma",
        email="chiamaka.demo@example.com", phone="08012345678", address="12 Unity Road, Kazaure",
    ),
    dict(
        reg_no="2308-2301-0004", name="David Adeyemi", first_login=True, onboarding_completed=True,
        email_verified=True,
        student_type="National", state="Oyo", lga="Ibadan North", nationality="Nigeria",
        dob=date(1999, 5, 9), gender="Male", semester="2nd Semester",
        department="Information Technology", course="HND Information Technology",
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
        print(f"\nDone. {created} student(s) created. Default password for first_login=True accounts: {DEFAULT_PASSWORD}")


if __name__ == "__main__":
    seed()
