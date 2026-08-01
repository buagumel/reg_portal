from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, LoginManager, current_user, logout_user, login_required
import os
import time
import uuid
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, generate_csrf
from extensions import mail, Message
from models import (
    db, User, RegisteredCourse, StudentRegistration, Payment, PaymentCategory,
)
from constants_file import (
    SECRET_KEY, MAIL_SERVER, MAIL_USERNAME, MAIL_PASSWORD
)
from auth_helpers import get_gate_redirect, validate_password_strength, is_valid_email
from onboarding_helpers import (
    start_otp_session, register_failed_otp_attempt, otp_attempts_exceeded,
    clear_otp_session, save_profile_picture, MAX_OTP_ATTEMPTS
)
from services.student_profile import get_profile_display
from services.registration import (
    get_registration_status_context, register_student, get_registration_history,
    get_active_period, RegistrationError,
    add_course, drop_course, submit_registration, get_add_drop_context,
)
from services.course import get_available_courses
from services.course_history import get_courses_by_semester
from services.audit import log_action
from services.notification import (
    create_notification, get_notifications, get_summary_counts,
    mark_read, mark_unread, mark_all_read, archive_notification, delete_notification,
    notify_registration_window_events,
)
from services.profile import (
    update_contact_info, change_password as profile_change_password,
    update_profile_picture, delete_profile_picture,
)
from services.payment import (
    get_active_categories, create_payment, initiate_payment, verify_payment,
    retry_verification, cancel_payment, get_payment_history,
    get_summary_counts as get_payment_summary_counts,
)
from services.payment_gateway import get_gateway, GatewayError, build_checkout_url
from services.errors import PaymentError

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['PAYMENT_GATEWAY_MODE'] = 'remita'
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

@app.context_processor
def inject_unread_notification_count():
    if current_user.is_authenticated:
        return {'unread_notification_count': get_summary_counts(current_user)['unread']}
    return {}

@app.route('/update-profile', methods=['POST'])
@login_required
def update_profile():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    phone = data.get('phone', '').strip()
    if not phone:
        return jsonify({'success': False, 'message': 'Phone number is required'}), 400

    address = data.get('address', '').strip()
    emergency_contact = data.get('emergency_contact', '').strip()
    blood_group = data.get('blood_group', '').strip()

    update_contact_info(
        current_user, phone=phone, address=address,
        emergency_contact=emergency_contact, blood_group=blood_group,
    )

    return jsonify({
        'success': True,
        'message': 'Profile updated successfully',
        'phone': current_user.formatted_phone,
        'email': current_user.email,
    })

@app.route('/profile/picture', methods=['POST'])
@login_required
def profile_picture_upload():
    file_storage = request.files.get('profile_picture')
    if not file_storage:
        return jsonify({'success': False, 'message': 'No file provided.'}), 400

    upload_folder = os.path.join(app.static_folder, 'uploads')
    try:
        update_profile_picture(current_user, file_storage, upload_folder)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({
        'success': True,
        'message': 'Profile picture updated.',
        'profile_picture': url_for('static', filename=current_user.profile_picture),
    })


@app.route('/profile/picture/delete', methods=['POST'])
@login_required
def profile_picture_delete():
    try:
        delete_profile_picture(current_user, app.static_folder)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'message': 'Profile picture removed.'})


@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    current = data.get('current', '').strip()
    new_pass = data.get('new', '').strip()
    confirm = data.get('confirm', '').strip()

    try:
        profile_change_password(current_user, current, new_pass, confirm)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

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

    create_notification(
        current_user, 'Welcome to the Student Portal',
        'Your profile setup is complete. Welcome aboard!',
        category='profile', priority='medium',
    )

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
@login_required
def dashboard():
    notify_registration_window_events(current_user)
    return render_template('dashboard.html', profile_display=get_profile_display(current_user))













@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))



@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', profile_display=get_profile_display(current_user))

@app.route('/announcements')
@login_required
def announcements():
    return render_template(
        'announcements.html',
        summary=get_summary_counts(current_user),
        notifications=get_notifications(current_user),
    )


@app.route('/notifications/data')
@login_required
def notifications_data():
    category = request.args.get('category') or None
    priority = request.args.get('priority') or None
    read_status = request.args.get('read_status') or None
    date_from = request.args.get('date_from') or None
    date_to = request.args.get('date_to') or None
    search = request.args.get('search') or None
    archived = request.args.get('archived') == 'true'

    notifications = get_notifications(
        current_user, category=category, priority=priority, read_status=read_status,
        date_from=date_from, date_to=date_to, search=search, archived=archived,
    )

    def notif_json(n):
        return {
            'id': n.id, 'title': n.title, 'message': n.message, 'category': n.category,
            'priority': n.priority, 'related_url': n.related_url,
            'created_at': n.created_at.strftime('%d %b %Y, %I:%M %p'),
            'is_read': n.read_at is not None,
            'is_archived': n.archived_at is not None,
        }

    return jsonify({
        'success': True,
        'notifications': [notif_json(n) for n in notifications],
        'summary': get_summary_counts(current_user),
    })


@app.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def notification_mark_read(notification_id):
    notification = mark_read(current_user, notification_id)
    if notification is None:
        return jsonify({'success': False, 'message': 'Notification not found.'}), 404
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@app.route('/notifications/<int:notification_id>/unread', methods=['POST'])
@login_required
def notification_mark_unread(notification_id):
    notification = mark_unread(current_user, notification_id)
    if notification is None:
        return jsonify({'success': False, 'message': 'Notification not found.'}), 404
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@app.route('/notifications/<int:notification_id>/archive', methods=['POST'])
@login_required
def notification_archive(notification_id):
    notification = archive_notification(current_user, notification_id)
    if notification is None:
        return jsonify({'success': False, 'message': 'Notification not found.'}), 404
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@app.route('/notifications/<int:notification_id>/delete', methods=['POST'])
@login_required
def notification_delete(notification_id):
    notification = delete_notification(current_user, notification_id)
    if notification is None:
        return jsonify({'success': False, 'message': 'Notification not found.'}), 404
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@app.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def notification_mark_all_read():
    mark_all_read(current_user)
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@app.route('/courses')
def courses():
    return "This is the courses page.";


@app.route('/payment/registration/<int:registration_id>')
@login_required
def payment_registration_summary(registration_id):
    registration = StudentRegistration.query.filter_by(id=registration_id, user_id=current_user.id).first_or_404()
    if registration.payment_status == 'paid':
        flash('This registration has already been paid for.')
        return redirect(url_for('registration'))
    payment = (
        Payment.query
        .filter_by(registration_id=registration.id, status='pending')
        .order_by(Payment.id.desc())
        .first()
    )
    return render_template('payment_summary.html', registration=registration, payment=payment)


@app.route('/payment/<reference>/initiate', methods=['POST'])
@login_required
def payment_initiate(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status != 'pending':
        return jsonify({'success': False, 'message': 'This payment is no longer pending.'}), 400
    gateway = get_gateway(app)
    try:
        checkout_url = initiate_payment(gateway, payment, current_user)
    except GatewayError as e:
        return jsonify({'success': False, 'message': str(e)}), 502
    return jsonify({'success': True, 'redirect': checkout_url})


@app.route('/payment/callback')
def payment_callback():
    # No @login_required: Remita's redirect may arrive in a context where
    # the session cookie isn't guaranteed, so this route is scoped instead
    # by the payment's unique unguessable reference token (like a password
    # reset link). It performs no write on behalf of a user identity beyond
    # what verify_payment does to the Payment/Registration it already owns.
    order_id = request.args.get('orderId') or request.args.get('orderid') or request.args.get('reference')
    payment = Payment.query.filter_by(reference=order_id).first() if order_id else None
    if payment is None:
        flash('Could not identify the payment to verify.')
        return redirect(url_for('payments_history'))

    gateway = get_gateway(app)
    verify_payment(gateway, payment)
    return render_template('payment_callback.html', payment=payment)


@app.route('/payment/<reference>/resume')
@login_required
def payment_resume(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status not in ('pending', 'timeout'):
        flash('This payment is no longer pending.')
        return redirect(url_for('payments_history'))

    if payment.rrr:
        return redirect(build_checkout_url(payment.rrr))

    gateway = get_gateway(app)
    try:
        checkout_url = initiate_payment(gateway, payment, current_user)
    except GatewayError:
        flash('Could not reach the payment gateway. Please try again shortly.')
        return redirect(url_for('payments_history'))
    return redirect(checkout_url)


@app.route('/payment/<reference>/cancel', methods=['POST'])
@login_required
def payment_cancel(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    try:
        cancel_payment(payment)
    except PaymentError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    return jsonify({'success': True, 'message': 'Payment cancelled.'})


@app.route('/payment/<reference>/retry', methods=['POST'])
@login_required
def payment_retry(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    gateway = get_gateway(app)
    retry_verification(gateway, payment)
    return jsonify({'success': True, 'status': payment.status})


@app.route('/payment/create', methods=['GET'])
@login_required
def payment_create_page():
    categories = [c for c in get_active_categories() if c.default_amount is not None]
    idempotency_key = str(uuid.uuid4())
    return render_template('payment_create.html', categories=categories, idempotency_key=idempotency_key)


@app.route('/payment/create', methods=['POST'])
@login_required
def payment_create_submit():
    data = request.get_json() or {}
    idempotency_key = data.get('idempotency_key', '')
    selections = data.get('items', [])
    if not idempotency_key:
        return jsonify({'success': False, 'message': 'Invalid request.'}), 400

    item_specs = []
    for sel in selections:
        if not isinstance(sel, dict):
            continue
        category = PaymentCategory.query.filter_by(id=sel.get('category_id'), is_active=True).first()
        if category is None or category.default_amount is None:
            continue
        try:
            quantity = int(sel.get('quantity', 1))
        except (TypeError, ValueError):
            quantity = 1
        quantity = max(1, min(quantity, 10))
        item_specs.append((category, quantity, category.default_amount))

    try:
        payment = create_payment(current_user, item_specs, idempotency_key)
    except PaymentError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    gateway = get_gateway(app)
    try:
        checkout_url = initiate_payment(gateway, payment, current_user)
    except GatewayError as e:
        return jsonify({'success': False, 'message': str(e)}), 502

    return jsonify({'success': True, 'redirect': checkout_url})


@app.route('/registration')
@login_required
def registration():
    notify_registration_window_events(current_user)
    return render_template(
        'registration.html',
        status=get_registration_status_context(current_user),
        history=get_registration_history(current_user),
    )


@app.route('/registration/register', methods=['POST'])
@login_required
def registration_register():
    period = get_active_period()
    if period is None:
        return jsonify({'success': False, 'message': 'No registration period is currently configured.'}), 400

    try:
        reg = register_student(current_user, period)
    except RegistrationError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({
        'success': True,
        'message': 'Registration created. Redirecting to payment...',
        'redirect': url_for('payment_registration_summary', registration_id=reg.id),
    })


@app.route('/add_drop')
@login_required
def add_drop():
    context = get_add_drop_context(current_user)
    if context['period'] is None or context['student_registration'] is None:
        flash('Please complete semester registration before selecting courses.')
        return redirect(url_for('registration'))
    return render_template('add_drop.html')


@app.route('/add_drop/data')
@login_required
def add_drop_data():
    context = get_add_drop_context(current_user)
    period, student_registration = context['period'], context['student_registration']
    if period is None or student_registration is None:
        return jsonify({'success': False, 'message': 'No active registration found.'}), 400

    available = get_available_courses(current_user, period, student_registration)
    selected = RegisteredCourse.query.filter_by(student_registration_id=student_registration.id).all()

    def course_json(c):
        return {'id': c.id, 'code': c.code, 'title': c.title, 'credits': c.credits, 'type': c.course_type}

    return jsonify({
        'success': True,
        'session': period.academic_session.name,
        'semester': period.semester.name,
        'deadline': period.closes_at.strftime('%d %b %Y'),
        'closes_at_iso': period.closes_at.isoformat(),
        'min_credits': context['min_credits'],
        'max_credits': context['max_credits'],
        'credits_registered': student_registration.credits_registered,
        'courses_submitted': student_registration.courses_submitted,
        'available_courses': [course_json(c) for c in available],
        'selected_courses': [course_json(rc.course) for rc in selected],
    })


@app.route('/add_drop/add', methods=['POST'])
@login_required
def add_drop_add():
    data = request.get_json()
    if not data or 'course_id' not in data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    context = get_add_drop_context(current_user)
    period, student_registration = context['period'], context['student_registration']
    if period is None or student_registration is None:
        return jsonify({'success': False, 'message': 'No active registration found.'}), 400

    try:
        add_course(current_user, period, student_registration, data['course_id'])
    except RegistrationError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'credits_registered': student_registration.credits_registered})


@app.route('/add_drop/drop', methods=['POST'])
@login_required
def add_drop_drop():
    data = request.get_json()
    if not data or 'course_id' not in data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    context = get_add_drop_context(current_user)
    period, student_registration = context['period'], context['student_registration']
    if period is None or student_registration is None:
        return jsonify({'success': False, 'message': 'No active registration found.'}), 400

    try:
        drop_course(current_user, period, student_registration, data['course_id'])
    except RegistrationError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'credits_registered': student_registration.credits_registered})


@app.route('/add_drop/submit', methods=['POST'])
@login_required
def add_drop_submit():
    context = get_add_drop_context(current_user)
    period, student_registration = context['period'], context['student_registration']
    if period is None or student_registration is None:
        return jsonify({'success': False, 'message': 'No active registration found.'}), 400

    try:
        submit_registration(current_user, period, student_registration)
    except RegistrationError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'redirect': url_for('my_courses')})


@app.route('/registration/slip')
@login_required
def registration_slip():
    student_registration = (
        StudentRegistration.query
        .filter_by(user_id=current_user.id, courses_submitted=True)
        .order_by(StudentRegistration.registered_at.desc())
        .first()
    )
    if student_registration is None:
        flash('No submitted registration found to print.')
        return redirect(url_for('registration'))

    courses = RegisteredCourse.query.filter_by(student_registration_id=student_registration.id).all()
    return render_template('registration_slip.html', registration=student_registration, courses=courses)


@app.route('/my_courses')
@login_required
def my_courses():
    return render_template('my_courses.html', groups=get_courses_by_semester(current_user))


@app.route('/courses/<int:course_id>/details')
@login_required
def course_details(course_id):
    registered_course = RegisteredCourse.query.join(StudentRegistration).filter(
        RegisteredCourse.course_id == course_id,
        StudentRegistration.user_id == current_user.id,
    ).first()
    if registered_course is None:
        return jsonify({'success': False, 'message': 'Course not found.'}), 404

    course = registered_course.course
    return jsonify({
        'success': True,
        'code': course.code,
        'title': course.title,
        'credits': course.credits,
        'department': course.department,
        'semester': course.semester.name,
        'description': course.description or 'Not available',
        'instructor': course.instructor or 'Not available',
        'schedule': course.schedule or 'Not available',
    })

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

    log_action(current_user, 'email_changed', details=f'Email changed to {pending_email}')
    create_notification(
        current_user, 'Email address changed',
        f'Your account email was changed to {pending_email}.',
        category='profile', priority='medium',
    )

    clear_otp_session(session)

    return jsonify({
        'success': True,
        'message': 'Email updated and verified successfully.',
        'email': current_user.email,
        'email_verified': current_user.email_verified
    })


if __name__ == '__main__':
    app.run(debug=True, port=4050)