from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, LoginManager, current_user, logout_user, login_required
import os
from datetime import datetime, timezone
import time
import uuid
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, generate_csrf
from extensions import mail, Message
from models import (
    db, User
)
from constants_file import (
    SECRET_KEY, MAIL_SERVER, MAIL_USERNAME, MAIL_PASSWORD
)
import re
import random
import string

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['MAIL_SERVER'] = MAIL_SERVER 
app.config['MAIL_PORT'] = 587                           
app.config['MAIL_USE_TLS'] = True                      
app.config['MAIL_USERNAME'] = MAIL_USERNAME   
app.config['MAIL_PASSWORD'] =  MAIL_PASSWORD       
app.config['MAIL_DEFAULT_SENDER'] = ("JSPICT, Kazaure", app.config['MAIL_USERNAME'])

mail.init_app(app) 
db.init_app(app)

with app.app_context():
    db.create_all()

migrate = Migrate(app, db) 
csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'   # redirect to this view if not logged in
login_manager.login_message = "Please log in to access this page."

@login_manager.user_loader
def load_user(idn):
    return db.get_or_404(User, idn)

@app.before_request
def check_email_verification():
    # Endpoints that are exempt from the verification check
    exempt_endpoints = [
        'login', 'logout', 'reg', 'profile', 'static', 
        'send_email_code', 'verify_email_code', 
        'admin', 'verify_email'   # add your email verification route here
    ]

    # If user is authenticated and email is not verified
    if current_user.is_authenticated and not current_user.email_verified:
        # Allow access to exempt endpoints
        if request.endpoint in exempt_endpoints:
            return None

        # GET requests -> redirect to profile page
        if request.method == 'GET':
            return redirect(url_for('profile'))

        # Non-GET requests -> JSON error
        return jsonify({
            'success': False,
            'message': 'Verify email to perform action.'
        }), 403

@app.route('/reg', methods=['GET', 'POST'])
def register():
    """Dev mode only"""
    reg_no = "2308-2301-0032"
    password = "123456"
    phone = "08083404159"
    email = "abaa69640@gmail.com"
    name = "Muhammad Lawal Sabon-Kudi"
    student_type = "International"
    state = "Jigawa"
    lga = "Ringim"
    address = "13 Bakin Kura"
    nationality = "Nigeria"
    dob = datetime(2001, 1, 24)
    gender = "Male"
    
    new_user = User(reg_no=reg_no, 
                    phone=phone, 
                    email=email, 
                    name=name,
                    student_type=student_type,
                    state=state, lga=lga,
                    address=address,
                    nationality=nationality,
                    dob=dob,
                    gender=gender
                )
    
    new_user.set_password(password=password)
    db.session.add(new_user)
    db.session.commit()

    return render_template('dashboard')
    

@app.route('/update-profile', methods=['POST'])
@login_required
def update_profile():
    time.sleep(5)
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    phone = data.get('phone', '').strip()

    # Basic validation
    if not phone:
        return jsonify({'success': False, 'message': 'Phone number is required'}), 400

    # Update
    current_user.phone = phone
    db.session.commit()

    # In your update_profile route, after commit:
    return jsonify({
        'success': True,
        'message': 'Profile updated successfully',
        'phone': current_user.formatted_phone,
        'email': current_user.email
    })

@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    current = data.get('current', '').strip()
    new_pass = data.get('new', '').strip()
    confirm = data.get('confirm', '').strip()

    # Basic validation
    if not current:
        return jsonify({'success': False, 'message': 'Current password is required'}), 400
    if not new_pass or len(new_pass) < 6:
        return jsonify({'success': False, 'message': 'New password must be at least 6 characters'}), 400
    if new_pass != confirm:
        return jsonify({'success': False, 'message': 'Passwords do not match'}), 400

    # Verify current password
    if not current_user.check_password(current):
        return jsonify({'success': False, 'message': 'Current password is incorrect'}), 400

    # Set new password
    current_user.set_password(new_pass)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Password changed successfully'})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        identifier = request.form.get('studentId', '').strip()
        password = request.form.get('password', '').strip()
        remember = True if request.form.get('rememberCheck') else False
        show_password = True if request.form.get('show_password') == 'on' else False

        user = User.query.filter(
            (User.reg_no == identifier) | (User.email == identifier)
        ).first()

        if user and user.check_password(password):
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            page_to_go = url_for('dashboard') if current_user.email_verified else url_for('profile')
            return redirect(next_page or page_to_go)
        else:
            # Render again with the submitted values
            return render_template(
                'login.html',
                error="Invalid registration number/email or password.",
                studentId=identifier,
                password=password,
                remember=remember,
                show_password=show_password
            )

    return render_template('login.html')

@app.route('/')
# @login_required
def dashboard():
    return render_template('dashboard.html')













@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))



@app.route('/profile')
def profile():
    return render_template('profile.html')

@app.route('/announcements')
def announcements():
    return render_template('announcements.html')


@app.route('/courses')
def courses():
    return "This is the courses page.";


@app.route('/pay_summary')
def pay_summary():
    return render_template('payment_summary.html')



@app.route('/registration')
def registration():
    return render_template('registration.html')


@app.route('/add_drop')
def add_drop():
    return render_template('add_drop.html')


@app.route('/add')
def add():
    return render_template('add.html')


@app.route('/my_courses')
def my_courses():
    return render_template('my_courses.html')

@app.route('/payments_history')
def payments_history():
    return render_template('payments_history.html')

@app.route('/admin')
def admin():
    return render_template('admin/admin_login.html')

@app.route('/send-email-code', methods=['POST'])
@login_required
def send_email_code():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    new_email = data.get('new_email', '').strip()
    if not new_email:
        return jsonify({'success': False, 'message': 'Email is required'}), 400
    if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', new_email):
        return jsonify({'success': False, 'message': 'Invalid email format'}), 400

    # Check if email already used by another user
    existing = User.query.filter(User.email == new_email, User.id != current_user.id).first()
    if existing:
        return jsonify({'success': False, 'message': 'Email already in use'}), 400

    # Generate 6-digit code
    code = ''.join(random.choices(string.digits, k=6))
    # Store in session with expiry (5 minutes)
    session['email_verification_code'] = code
    session['email_verification_expiry'] = time.time() + 300
    session['pending_email'] = new_email

    # Send email
    try:
        msg = Message('Email Verification Code', recipients=[new_email])
        msg.body = f'Your verification code is: {code}\nThis code expires in 5 minutes.'
        mail.send(msg)
    except Exception as e:
        # Log the error if needed: app.logger.error(str(e))
        return jsonify({'success': False, 'message': 'Failed to send email. Please try again.'}), 500

    return jsonify({'success': True, 'message': 'Verification code sent to your email.'})

@app.route('/verify-email-code', methods=['POST'])
@login_required
def verify_email_code():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    code = data.get('code', '').strip()
    new_email = data.get('new_email', '').strip()
    if not code:
        return jsonify({'success': False, 'message': 'Verification code is required'}), 400

    stored_code = session.get('email_verification_code')
    expiry = session.get('email_verification_expiry')
    pending_email = session.get('pending_email')

    if not stored_code or not expiry or not pending_email:
        return jsonify({'success': False, 'message': 'No pending verification. Please request a new code.'}), 400

    if time.time() > expiry:
        session.pop('email_verification_code', None)
        session.pop('email_verification_expiry', None)
        session.pop('pending_email', None)
        return jsonify({'success': False, 'message': 'Verification code expired. Please request a new one.'}), 400

    if stored_code != code:
        return jsonify({'success': False, 'message': 'Invalid verification code.'}), 400

    if new_email and new_email != pending_email:
        return jsonify({'success': False, 'message': 'Email mismatch. Please request a new code.'}), 400

    # Update email and mark as verified
    current_user.email = pending_email
    current_user.email_verified = True   # <-- KEY CHANGE
    db.session.commit()

    # Clear session
    session.pop('email_verification_code', None)
    session.pop('email_verification_expiry', None)
    session.pop('pending_email', None)

    return jsonify({
        'success': True,
        'message': 'Email updated and verified successfully.',
        'email': current_user.email,
        'email_verified': current_user.email_verified
    })
    
    
if __name__ == '__main__':    
    app.run(debug=True, port=4050)