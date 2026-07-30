from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, LoginManager, current_user, logout_user, login_required
import os
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
from auth_helpers import get_gate_redirect, validate_password_strength, is_valid_email
from onboarding_helpers import (
    start_otp_session, register_failed_otp_attempt, otp_attempts_exceeded,
    clear_otp_session, save_profile_picture, MAX_OTP_ATTEMPTS
)

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
def enforce_onboarding_gate():
    if not current_user.is_authenticated:
        return None

    exempt_endpoints = {
        'login', 'logout', 'static', 'admin',
        'force_password_change',
        'onboarding', 'onboarding_save_info', 'onboarding_complete',
        'send_email_code', 'verify_email_code',
        'profile',
    }
    if request.endpoint in exempt_endpoints:
        return None

    redirect_endpoint = get_gate_redirect(current_user)
    if redirect_endpoint is None:
        return None

    if request.method == 'GET':
        return redirect(url_for(redirect_endpoint))

    return jsonify({'success': False, 'message': 'Please complete the required step before continuing.'}), 403

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

    if not current:
        return jsonify({'success': False, 'message': 'Current password is required'}), 400

    failed_rules = validate_password_strength(new_pass)
    if failed_rules:
        return jsonify({'success': False, 'message': 'Password must contain ' + ', '.join(failed_rules) + '.'}), 400
    if new_pass != confirm:
        return jsonify({'success': False, 'message': 'Passwords do not match'}), 400

    if not current_user.check_password(current):
        return jsonify({'success': False, 'message': 'Current password is incorrect'}), 400

    current_user.set_password(new_pass)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Password changed successfully'})

@app.route('/force-password-change', methods=['GET', 'POST'])
@login_required
def force_password_change():
    if request.method == 'GET':
        if not current_user.first_login:
            return redirect(url_for(get_gate_redirect(current_user) or 'dashboard'))
        return render_template('force_password_change.html')

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    new_pass = data.get('new', '').strip()
    confirm = data.get('confirm', '').strip()

    if not new_pass:
        return jsonify({'success': False, 'message': 'New password is required'}), 400
    if new_pass != confirm:
        return jsonify({'success': False, 'message': 'Passwords do not match'}), 400

    failed_rules = validate_password_strength(new_pass)
    if failed_rules:
        return jsonify({'success': False, 'message': 'Password must contain ' + ', '.join(failed_rules) + '.'}), 400

    current_user.set_password(new_pass)
    current_user.first_login = False
    db.session.commit()

    redirect_endpoint = get_gate_redirect(current_user) or 'dashboard'
    return jsonify({'success': True, 'message': 'Password changed successfully.', 'redirect': url_for(redirect_endpoint)})

@app.route('/onboarding')
@login_required
def onboarding():
    target = get_gate_redirect(current_user)
    if target != 'onboarding':
        return redirect(url_for(target or 'dashboard'))
    return render_template('onboarding.html')

@app.route('/onboarding/save-info', methods=['POST'])
@login_required
def onboarding_save_info():
    if get_gate_redirect(current_user) != 'onboarding':
        return jsonify({'success': False, 'message': 'Onboarding is already complete.'}), 403

    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    address = request.form.get('address', '').strip()
    picture = request.files.get('profile_picture')

    errors = {}
    if not email:
        errors['email'] = 'Email is required'
    elif not is_valid_email(email):
        errors['email'] = 'Invalid email format'
    else:
        existing = User.query.filter(User.email == email, User.id != current_user.id).first()
        if existing:
            errors['email'] = 'Email already in use'

    if not phone:
        errors['phone'] = 'Phone number is required'
    if not address:
        errors['address'] = 'Address is required'

    picture_path, picture_error = save_profile_picture(
        picture, current_user.reg_no,
        os.path.join(app.static_folder, 'uploads')
    )
    if picture_error:
        errors['profile_picture'] = picture_error

    if errors:
        return jsonify({'success': False, 'message': 'Please correct the highlighted fields.', 'errors': errors}), 400

    if email != current_user.email:
        current_user.email_verified = False
    current_user.email = email
    current_user.phone = phone
    current_user.address = address
    current_user.profile_picture = picture_path
    db.session.commit()

    return jsonify({'success': True, 'message': 'Information saved.'})

@app.route('/onboarding/complete', methods=['POST'])
@login_required
def onboarding_complete():
    if get_gate_redirect(current_user) != 'onboarding':
        return jsonify({'success': False, 'message': 'Onboarding is already complete.'}), 403

    if not current_user.email_verified:
        return jsonify({'success': False, 'message': 'Please verify your email before completing onboarding.'}), 400

    current_user.onboarding_completed = True
    db.session.commit()

    try:
        msg = Message('Welcome to JSPICT Student Portal', recipients=[current_user.email])
        msg.body = f'Hi {current_user.name},\n\nYour profile setup is complete. Welcome to the JSPICT Student Portal!'
        mail.send(msg)
    except Exception:
        app.logger.warning('Failed to send welcome email to %s', current_user.email)

    return jsonify({'success': True, 'message': 'Onboarding complete!', 'redirect': url_for('dashboard')})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        redirect_endpoint = get_gate_redirect(current_user) or 'dashboard'
        return redirect(url_for(redirect_endpoint))

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
            redirect_endpoint = get_gate_redirect(current_user) or 'dashboard'
            return redirect(next_page or url_for(redirect_endpoint))
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
    if not is_valid_email(new_email):
        return jsonify({'success': False, 'message': 'Invalid email format'}), 400

    existing = User.query.filter(User.email == new_email, User.id != current_user.id).first()
    if existing:
        return jsonify({'success': False, 'message': 'Email already in use'}), 400

    code = start_otp_session(session, new_email)

    try:
        msg = Message('Email Verification Code', recipients=[new_email])
        msg.body = f'Your verification code is: {code}\nThis code expires in 5 minutes.'
        mail.send(msg)
    except Exception:
        clear_otp_session(session)
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
        clear_otp_session(session)
        return jsonify({'success': False, 'message': 'Verification code expired. Please request a new one.'}), 400

    if stored_code != code:
        attempts = register_failed_otp_attempt(session)
        if otp_attempts_exceeded(session):
            clear_otp_session(session)
            return jsonify({
                'success': False,
                'message': 'Maximum attempts exceeded. Please request a new code.',
                'max_attempts_reached': True
            }), 400
        remaining = MAX_OTP_ATTEMPTS - attempts
        return jsonify({'success': False, 'message': f'Invalid verification code. {remaining} attempt(s) remaining.'}), 400

    if new_email and new_email != pending_email:
        return jsonify({'success': False, 'message': 'Email mismatch. Please request a new code.'}), 400

    current_user.email = pending_email
    current_user.email_verified = True
    db.session.commit()

    clear_otp_session(session)

    return jsonify({
        'success': True,
        'message': 'Email updated and verified successfully.',
        'email': current_user.email,
        'email_verified': current_user.email_verified
    })


if __name__ == '__main__':
    app.run(debug=True, port=4050)