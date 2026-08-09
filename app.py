from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, Response, abort
from flask_login import login_user, LoginManager, current_user, logout_user, login_required
import os
import time
import uuid
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, generate_csrf
from extensions import mail, Message
from models import (
    db, User, RegisteredCourse, StudentRegistration, Payment, PaymentCategory, AdminUser, now_lagos, Programme,
    RegistrationPeriod,
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
    add_course, drop_course, submit_registration, get_add_drop_context, get_effective_add_drop_deadline,
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
from services.fee_structure import get_payable_categories, resolve_amount
from services.admin_fee_structure import (
    list_fee_structures, get_fee_structure, create_fee_structure,
    update_fee_structure, delete_fee_structure,
)
from services.payment_gateway import get_gateway, GatewayError, build_checkout_url
from services.errors import PaymentError
from services.receipt import get_or_create_receipt, render_pdf, send_receipt_email
from services.admin_auth import authenticate_admin, change_admin_password
from services.admin_audit import log_admin_action
from services.admin_permission import admin_required, permission_required, get_visible_quick_actions
from services.admin_dashboard import get_dashboard_summary, get_activity_feed
from services.admin_department import (
    list_departments, get_department, get_department_detail,
    create_department, update_department, set_department_status,
)
from services.admin_programme import (
    list_programmes, get_programme, get_programme_detail,
    create_programme, update_programme, set_programme_status,
    get_programme_department_ids, set_programme_departments,
    list_departments_for_programme_checkboxes,
)
from services.admin_validation import (
    is_department_code_unique, is_programme_code_unique, validate_credit_range, valid_levels_for_programme,
    LEVELS_BY_PROGRAM_TYPE, is_session_name_unique, is_fee_structure_scope_unique,
)
from services.admin_session import (
    list_sessions, get_session, create_session, update_session, archive_session, clone_session,
    list_semesters, list_semesters_for_programme, list_periods, get_period, create_period, update_period, activate_period,
    list_holidays, create_holiday, list_inactive_periods,
)
from services.admin_course import list_courses, get_course, create_course, update_course, set_course_status, get_course_detail, set_assessment_components, get_enrollment_count
from services.admin_course_catalog import (
    list_master_courses, get_master_course, get_master_course_detail,
    create_master_course, update_master_course, set_master_course_status,
    list_master_courses_for_picker, set_prerequisites, set_corequisites,
)
from services.admin_export import export_csv, export_excel, VALID_DATA_TYPES
from services.admin_registration import (
    list_periods_for_selector, get_oversight_metrics, admin_add_course, admin_drop_course,
    set_registration_lock, extend_deadline, reopen_registration, approve_exception,
)
from services.admin_onboarding import (
    get_onboarding_summary, get_onboarding_analytics, reset_onboarding, manually_verify_email, mark_onboarding_complete,
)
from services.admin_permission import has_permission
from services.admin_department import list_active_departments
from services.admin_validation import is_course_code_unique, is_course_catalog_code_unique
from services.course_import import import_courses_csv, preview_courses_csv
from models import CourseImportJob
from services.admin_student import (
    list_active_programmes, list_students, get_student, get_student_profile,
    create_student, update_student, set_account_status, reset_student_password, resend_verification,
    bulk_set_status, bulk_reset_password, bulk_assign_department, bulk_assign_programme,
)
from services.student_import import import_students_csv, preview_students_csv
from models import StudentImportJob

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

ADMIN_SESSION_TIMEOUT_SECONDS = 15 * 60

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
    if idn.startswith('admin:'):
        try:
            return AdminUser.query.get(int(idn.split(':', 1)[1]))
        except (ValueError, IndexError):
            return None
    return db.get_or_404(User, idn)

@app.before_request
def enforce_onboarding_gate():
    if not current_user.is_authenticated:
        return None
    if isinstance(current_user, AdminUser):
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

@app.before_request
def enforce_admin_session_timeout():
    if not current_user.is_authenticated or not isinstance(current_user, AdminUser):
        return None
    if request.endpoint in ('admin_login', 'static'):
        return None

    now_ts = time.time()
    last_activity = session.get('admin_last_activity')
    if last_activity is not None and (now_ts - last_activity) > ADMIN_SESSION_TIMEOUT_SECONDS:
        logout_user()
        session.pop('admin_last_activity', None)
        flash('Your admin session expired due to inactivity. Please log in again.')
        return redirect(url_for('admin_login'))

    session['admin_last_activity'] = now_ts

    onboarding_exempt_endpoints = {'admin_force_password_change', 'admin_logout', 'static'}
    if current_user.first_login and request.endpoint not in onboarding_exempt_endpoints:
        return redirect(url_for('admin_force_password_change'))

    return None

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
    current_user.onboarding_completed_at = now_lagos()
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
            if user.account_status != 'active':
                status_messages = {
                    'suspended': 'Your account has been suspended. Please contact administration.',
                    'deactivated': 'Your account has been deactivated. Please contact administration.',
                }
                return render_template(
                    'login.html',
                    error=status_messages.get(user.account_status, 'Your account is not active. Please contact administration.'),
                    studentId=identifier,
                    password=password,
                    remember=remember,
                    show_password=show_password
                )
            user.last_login_at = now_lagos()
            db.session.commit()
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
    recent_payments, _ = get_payment_history(current_user, page=1, per_page=5)
    return render_template(
        'dashboard.html',
        profile_display=get_profile_display(current_user),
        recent_payments=recent_payments,
        status=get_registration_status_context(current_user),
    )













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
        .filter(
            Payment.registration_id == registration.id,
            Payment.status.in_(('pending', 'timeout')),
        )
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

    if payment.rrr:
        return jsonify({'success': True, 'redirect': build_checkout_url(payment.rrr)})

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


@app.route('/payment/<reference>/receipt')
@login_required
def payment_receipt(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status != 'successful':
        flash('Receipt is only available for successful payments.')
        return redirect(url_for('payments_history'))
    receipt = get_or_create_receipt(payment)
    return render_template('payment_receipt.html', payment=payment, receipt=receipt)


@app.route('/payment/<reference>/receipt.pdf')
@login_required
def payment_receipt_pdf(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status != 'successful':
        flash('Receipt is only available for successful payments.')
        return redirect(url_for('payments_history'))
    receipt = get_or_create_receipt(payment)
    pdf_bytes = render_pdf(payment, receipt)
    return Response(pdf_bytes, mimetype='application/pdf', headers={
        'Content-Disposition': f'attachment; filename={receipt.receipt_number}.pdf'
    })


@app.route('/payment/<reference>/resend-receipt', methods=['POST'])
@login_required
def payment_resend_receipt(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status != 'successful':
        return jsonify({'success': False, 'message': 'No receipt available for this payment.'}), 400
    receipt = get_or_create_receipt(payment)
    send_receipt_email(payment, receipt)
    return jsonify({'success': True, 'message': 'Receipt email sent.'})


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
    # Namespace the client-supplied key by user, defensively — belt-and-braces
    # on top of create_payment's own user_id-scoped lookup, so a client can
    # never collide with (and get handed back) another user's payment even if
    # the query scoping above were ever weakened.
    idempotency_key = f'{current_user.id}:{idempotency_key}'

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

    if payment.status != 'pending':
        return jsonify({'success': False, 'message': 'This payment has already been processed.'}), 400

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
    period = get_active_period(current_user)
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
    effective_deadline = get_effective_add_drop_deadline(period, student_registration)

    def course_json(c):
        return {'id': c.id, 'code': c.code, 'title': c.title, 'credits': c.credits, 'type': c.course_type}

    return jsonify({
        'success': True,
        'session': period.academic_session.name,
        'semester': period.semester.name,
        'deadline': effective_deadline.strftime('%d %b %Y'),
        'closes_at_iso': effective_deadline.isoformat(),
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
@login_required
def payments_history():
    summary = get_payment_summary_counts(current_user)
    return render_template('payments_history.html', summary=summary)


@app.route('/payments_history/data')
@login_required
def payments_history_data():
    status = request.args.get('status') or None
    search = request.args.get('search') or None
    date_from = request.args.get('date_from') or None
    date_to = request.args.get('date_to') or None
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    per_page = 10

    items, total = get_payment_history(
        current_user, status=status, search=search,
        date_from=date_from, date_to=date_to, page=page, per_page=per_page,
    )
    raw_summary = get_payment_summary_counts(current_user)

    return jsonify({
        'success': True,
        'page': page,
        'per_page': per_page,
        'total': total,
        'summary': {
            'total': raw_summary['total'],
            'total_amount_paid': float(raw_summary['total_amount_paid']),
            'pending': raw_summary['pending'],
            'cancelled': raw_summary['cancelled'],
        },
        'payments': [
            {
                'reference': p.reference,
                'rrr': p.rrr or '-',
                'description': ', '.join(i.description for i in p.items) or '-',
                'category': p.items[0].category.name if p.items else '-',
                'amount': float(p.total_amount),
                'status': p.status,
                'date': p.initiated_at.strftime('%d %b %Y'),
                'session': p.registration.registration_period.academic_session.name if p.registration else '-',
                'semester': p.registration.registration_period.semester.name if p.registration else '-',
                'method': 'Remita',
                'can_retry': p.status in ('pending', 'timeout', 'failed'),
                'can_resume': p.status in ('pending', 'timeout'),
                'has_receipt': p.status == 'successful',
            }
            for p in items
        ],
    })

@app.route('/admin')
def admin():
    return redirect(url_for('admin_login'))


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and isinstance(current_user, AdminUser):
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        remember = True if request.form.get('rememberCheck') else False

        admin_user = authenticate_admin(email, password, ip_address=request.remote_addr)
        if admin_user:
            login_user(admin_user, remember=remember)
            session['admin_last_activity'] = time.time()
            if admin_user.first_login:
                return redirect(url_for('admin_force_password_change'))
            return redirect(url_for('admin_dashboard'))

        return render_template('admin/admin_login.html', error='Invalid email or password.', email=email, remember=remember)

    return render_template('admin/admin_login.html')


@app.route('/admin/forgot-password', methods=['GET', 'POST'])
def admin_forgot_password():
    if request.method == 'GET':
        return render_template('admin/admin_forgot_password.html')

    email = request.form.get('email', '').strip()
    admin_user = AdminUser.query.filter_by(email=email).first()

    # Start the OTP session unconditionally so the code-entry page is
    # reached the same way whether or not the email matched an account —
    # otherwise the code-entry page's own session guard would bounce
    # non-matching emails straight back, revealing which emails are admins.
    code = start_otp_session(session, email)

    branch_started_at = time.time()

    if admin_user:
        session['admin_reset_admin_id'] = admin_user.id
        try:
            msg = Message('Admin Password Reset Code', recipients=[email])
            msg.body = f'Your password reset code is: {code}\nThis code expires in 5 minutes.'
            mail.send(msg)
        except Exception:
            app.logger.warning('Failed to send admin password reset email to %s', email)

    # Pad the response to a fixed minimum duration so the presence/absence of
    # the network-bound mail.send() call above can't be inferred from response
    # timing — a flat sleep on only the non-match branch doesn't work, since
    # mail.send() itself varies well beyond any small fixed delay. This isn't a
    # perfect fix (a slow mail.send() can still exceed the floor), but it closes
    # the channel for the common case without needing a background task queue.
    MIN_RESPONSE_SECONDS = 1.5
    elapsed = time.time() - branch_started_at
    if elapsed < MIN_RESPONSE_SECONDS:
        time.sleep(MIN_RESPONSE_SECONDS - elapsed)

    # Always redirect the same way regardless of whether the email matched
    # an account, so this endpoint never reveals which emails are admins.
    return redirect(url_for('admin_verify_reset_code'))


@app.route('/admin/verify-reset-code', methods=['GET', 'POST'])
def admin_verify_reset_code():
    if 'email_verification_code' not in session:
        return redirect(url_for('admin_forgot_password'))

    if request.method == 'GET':
        return render_template('admin/admin_verify_reset_code.html', email=session.get('pending_email'))

    data = request.get_json()
    code = (data.get('code', '') if data else '').strip()

    if otp_attempts_exceeded(session):
        clear_otp_session(session)
        session.pop('admin_reset_admin_id', None)
        return jsonify({'success': False, 'message': 'Too many attempts. Please request a new code.'}), 400

    if time.time() > session.get('email_verification_expiry', 0):
        clear_otp_session(session)
        session.pop('admin_reset_admin_id', None)
        return jsonify({'success': False, 'message': 'This code has expired. Please request a new one.'}), 400

    if code != session.get('email_verification_code'):
        register_failed_otp_attempt(session)
        return jsonify({'success': False, 'message': 'Incorrect code.'}), 400

    session['admin_reset_verified'] = True
    return jsonify({'success': True, 'redirect': url_for('admin_reset_password')})


@app.route('/admin/reset-password', methods=['GET', 'POST'])
def admin_reset_password():
    if not session.get('admin_reset_verified') or 'admin_reset_admin_id' not in session:
        return redirect(url_for('admin_forgot_password'))

    if request.method == 'GET':
        return render_template('admin/admin_reset_password.html')

    data = request.get_json()
    new_pass = (data.get('new', '') if data else '').strip()
    confirm = (data.get('confirm', '') if data else '').strip()

    if not new_pass or new_pass != confirm:
        return jsonify({'success': False, 'message': 'Passwords do not match'}), 400

    failed_rules = validate_password_strength(new_pass)
    if failed_rules:
        return jsonify({'success': False, 'message': 'Password must contain ' + ', '.join(failed_rules) + '.'}), 400

    admin_user = AdminUser.query.get(session['admin_reset_admin_id'])
    change_admin_password(admin_user, new_pass)
    log_admin_action(admin_user, 'password_reset', ip_address=request.remote_addr)

    clear_otp_session(session)
    session.pop('admin_reset_admin_id', None)
    session.pop('admin_reset_verified', None)

    return jsonify({
        'success': True,
        'message': 'Password reset successfully. Please log in.',
        'redirect': url_for('admin_login'),
    })


@app.route('/admin/logout')
@admin_required
def admin_logout():
    log_admin_action(current_user, 'logout', ip_address=request.remote_addr)
    logout_user()
    session.pop('admin_last_activity', None)
    return redirect(url_for('admin_login'))


@app.route('/admin/force-password-change', methods=['GET', 'POST'])
@admin_required
def admin_force_password_change():
    if request.method == 'GET':
        if not current_user.first_login:
            return redirect(url_for('admin_dashboard'))
        return render_template('admin/admin_force_password_change.html')

    if not current_user.first_login:
        return jsonify({'success': False, 'message': 'Use the profile settings to change your password.'}), 403

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

    change_admin_password(current_user, new_pass)
    log_admin_action(current_user, 'password_changed', ip_address=request.remote_addr)

    return jsonify({
        'success': True,
        'message': 'Password changed successfully.',
        'redirect': url_for('admin_dashboard'),
    })


@app.route('/admin/dashboard')
@permission_required('dashboard.view')
def admin_dashboard():
    summary = get_dashboard_summary()
    activity_feed = get_activity_feed(limit=20)
    quick_actions = get_visible_quick_actions(current_user)
    return render_template(
        'admin/admin_dashboard.html',
        summary=summary, activity_feed=activity_feed, quick_actions=quick_actions,
    )


@app.route('/admin/departments')
@permission_required('departments.manage')
def admin_departments():
    search = request.args.get('search', '').strip() or None
    status = request.args.get('status', '').strip() or None
    page = request.args.get('page', 1, type=int)
    result = list_departments(search=search, status=status, page=page)
    return render_template(
        'admin/departments.html', result=result, search=search or '', status=status or '',
    )


@app.route('/admin/departments/new', methods=['GET', 'POST'])
@permission_required('departments.manage')
def admin_department_new():
    if request.method == 'GET':
        return render_template('admin/department_form.html', department=None)

    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    faculty = request.form.get('faculty', '').strip()
    head_name = request.form.get('head_name', '').strip()

    if not name or not code:
        flash('Name and code are required.')
        return render_template('admin/department_form.html', department=None, form=request.form)
    if not is_department_code_unique(code):
        flash(f'Department code "{code}" is already in use.')
        return render_template('admin/department_form.html', department=None, form=request.form)

    department = create_department(name, code, faculty, head_name)
    log_admin_action(current_user, 'department_created', target_type='department', target_id=department.id,
                      details=f'name={name} code={code}', ip_address=request.remote_addr)
    flash(f'Department "{name}" created.')
    return redirect(url_for('admin_departments'))


@app.route('/admin/departments/<int:department_id>')
@permission_required('departments.manage')
def admin_department_detail(department_id):
    detail = get_department_detail(department_id)
    return render_template('admin/departments.html', detail=detail, result=None)


@app.route('/admin/departments/<int:department_id>/edit', methods=['GET', 'POST'])
@permission_required('departments.manage')
def admin_department_edit(department_id):
    department = get_department(department_id)
    if request.method == 'GET':
        return render_template('admin/department_form.html', department=department)

    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    faculty = request.form.get('faculty', '').strip()
    head_name = request.form.get('head_name', '').strip()

    if not name or not code:
        flash('Name and code are required.')
        return render_template('admin/department_form.html', department=department, form=request.form)
    if not is_department_code_unique(code, exclude_id=department_id):
        flash(f'Department code "{code}" is already in use.')
        return render_template('admin/department_form.html', department=department, form=request.form)

    update_department(department_id, name, code, faculty, head_name)
    log_admin_action(current_user, 'department_updated', target_type='department', target_id=department_id,
                      details=f'name={name} code={code}', ip_address=request.remote_addr)
    flash(f'Department "{name}" updated.')
    return redirect(url_for('admin_departments'))


@app.route('/admin/departments/<int:department_id>/activate', methods=['POST'])
@permission_required('departments.manage')
def admin_department_activate(department_id):
    set_department_status(department_id, 'active')
    log_admin_action(current_user, 'department_status_changed', target_type='department', target_id=department_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Department activated.')
    return redirect(url_for('admin_departments'))


@app.route('/admin/departments/<int:department_id>/deactivate', methods=['POST'])
@permission_required('departments.manage')
def admin_department_deactivate(department_id):
    set_department_status(department_id, 'inactive')
    log_admin_action(current_user, 'department_status_changed', target_type='department', target_id=department_id,
                      details='status=inactive', ip_address=request.remote_addr)
    flash('Department deactivated.')
    return redirect(url_for('admin_departments'))


@app.route('/admin/departments/<int:department_id>/archive', methods=['POST'])
@permission_required('departments.manage')
def admin_department_archive(department_id):
    set_department_status(department_id, 'archived')
    log_admin_action(current_user, 'department_status_changed', target_type='department', target_id=department_id,
                      details='status=archived', ip_address=request.remote_addr)
    flash('Department archived.')
    return redirect(url_for('admin_departments'))


@app.route('/admin/programmes')
@permission_required('programmes.manage')
def admin_programmes():
    search = request.args.get('search', '').strip() or None
    status = request.args.get('status', '').strip() or None
    page = request.args.get('page', 1, type=int)
    result = list_programmes(search=search, status=status, page=page)
    return render_template(
        'admin/programmes.html', result=result, search=search or '', status=status or '',
    )


@app.route('/admin/programmes/new', methods=['GET', 'POST'])
@permission_required('programmes.manage')
def admin_programme_new():
    if request.method == 'GET':
        return render_template('admin/programme_form.html', programme=None)

    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    program_type = request.form.get('program_type', '').strip()
    description = request.form.get('description', '').strip()
    uses_semesters = request.form.get('uses_semesters') == 'on'
    uses_terms = request.form.get('uses_terms') == 'on'
    duration = request.form.get('duration', '').strip()

    if not name or not code or not program_type:
        flash('Name, code, and programme type are required.')
        return render_template('admin/programme_form.html', programme=None, form=request.form)
    if program_type not in LEVELS_BY_PROGRAM_TYPE:
        flash('Invalid programme type.')
        return render_template('admin/programme_form.html', programme=None, form=request.form)
    if not is_programme_code_unique(code):
        flash(f'Programme code "{code}" is already in use.')
        return render_template('admin/programme_form.html', programme=None, form=request.form)

    programme = create_programme(name, code, program_type, description, uses_semesters, uses_terms, duration)
    log_admin_action(current_user, 'programme_created', target_type='programme', target_id=programme.id,
                      details=f'name={name} code={code}', ip_address=request.remote_addr)
    flash(f'Programme "{name}" created.')
    return redirect(url_for('admin_programmes'))


@app.route('/admin/programmes/<int:programme_id>')
@permission_required('programmes.manage')
def admin_programme_detail(programme_id):
    detail = get_programme_detail(programme_id)
    linked_ids = set(get_programme_department_ids(programme_id))
    all_departments = list_departments_for_programme_checkboxes(programme_id)
    return render_template(
        'admin/programmes.html', detail=detail, result=None,
        all_departments=all_departments, linked_ids=linked_ids,
    )


@app.route('/admin/programmes/<int:programme_id>/edit', methods=['GET', 'POST'])
@permission_required('programmes.manage')
def admin_programme_edit(programme_id):
    programme = get_programme(programme_id)
    if request.method == 'GET':
        return render_template('admin/programme_form.html', programme=programme)

    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    program_type = request.form.get('program_type', '').strip()
    description = request.form.get('description', '').strip()
    uses_semesters = request.form.get('uses_semesters') == 'on'
    uses_terms = request.form.get('uses_terms') == 'on'
    duration = request.form.get('duration', '').strip()

    if not name or not code or not program_type:
        flash('Name, code, and programme type are required.')
        return render_template('admin/programme_form.html', programme=programme, form=request.form)
    if program_type not in LEVELS_BY_PROGRAM_TYPE:
        flash('Invalid programme type.')
        return render_template('admin/programme_form.html', programme=programme, form=request.form)
    if not is_programme_code_unique(code, exclude_id=programme_id):
        flash(f'Programme code "{code}" is already in use.')
        return render_template('admin/programme_form.html', programme=programme, form=request.form)

    update_programme(programme_id, name, code, program_type, description, uses_semesters, uses_terms, duration)
    log_admin_action(current_user, 'programme_updated', target_type='programme', target_id=programme_id,
                      details=f'name={name} code={code}', ip_address=request.remote_addr)
    flash(f'Programme "{name}" updated.')
    return redirect(url_for('admin_programmes'))


@app.route('/admin/programmes/<int:programme_id>/departments', methods=['POST'])
@permission_required('programmes.manage')
def admin_programme_departments(programme_id):
    try:
        department_ids = [int(v) for v in request.form.getlist('department_ids')]
    except ValueError:
        flash('Invalid department selection.')
        return redirect(url_for('admin_programme_detail', programme_id=programme_id))
    set_programme_departments(programme_id, department_ids)
    log_admin_action(current_user, 'programme_departments_updated', target_type='programme', target_id=programme_id,
                      details=f'department_ids={department_ids}', ip_address=request.remote_addr)
    flash('Programme departments updated.')
    return redirect(url_for('admin_programme_detail', programme_id=programme_id))


@app.route('/admin/programmes/<int:programme_id>/activate', methods=['POST'])
@permission_required('programmes.manage')
def admin_programme_activate(programme_id):
    set_programme_status(programme_id, 'active')
    log_admin_action(current_user, 'programme_status_changed', target_type='programme', target_id=programme_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Programme activated.')
    return redirect(url_for('admin_programmes'))


@app.route('/admin/programmes/<int:programme_id>/archive', methods=['POST'])
@permission_required('programmes.manage')
def admin_programme_archive(programme_id):
    set_programme_status(programme_id, 'archived')
    log_admin_action(current_user, 'programme_status_changed', target_type='programme', target_id=programme_id,
                      details='status=archived', ip_address=request.remote_addr)
    flash('Programme archived.')
    return redirect(url_for('admin_programmes'))


@app.route('/admin/sessions')
@permission_required('sessions.manage')
def admin_sessions():
    programme_id = request.args.get('programme_id', type=int)
    sessions = list_sessions(programme_id=programme_id)
    return render_template(
        'admin/sessions.html', sessions=sessions,
        programmes=list_active_programmes(), selected_programme_id=programme_id,
    )


@app.route('/admin/sessions/new', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_sessions_new():
    if request.method == 'GET':
        return render_template('admin/session_form.html', session=None, programmes=list_active_programmes())

    name = request.form.get('name', '').strip()
    start_date = request.form.get('start_date') or None
    end_date = request.form.get('end_date') or None
    programme_id = request.form.get('programme_id', type=int) or None
    if not name:
        flash('Session name is required.')
        return render_template('admin/session_form.html', session=None, form=request.form, programmes=list_active_programmes())
    if not is_session_name_unique(name, programme_id):
        flash(f'A session named "{name}" already exists for this programme.')
        return render_template('admin/session_form.html', session=None, form=request.form, programmes=list_active_programmes())

    from datetime import date
    start_date = date.fromisoformat(start_date) if start_date else None
    end_date = date.fromisoformat(end_date) if end_date else None

    session_obj = create_session(name, start_date, end_date, programme_id=programme_id)
    log_admin_action(current_user, 'session_created', target_type='academic_session', target_id=session_obj.id,
                      details=f'name={name} programme_id={programme_id}', ip_address=request.remote_addr)
    flash(f'Session "{name}" created.')
    return redirect(url_for('admin_session_edit', session_id=session_obj.id))


@app.route('/admin/sessions/<int:session_id>/edit', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_session_edit(session_id):
    session_obj = get_session(session_id)
    # A session's programme_id can reference a Programme that has since been
    # archived (list_active_programmes() only returns active ones). If we
    # dropped it from the dropdown, an admin who edits the session without
    # touching the Programme field would submit no matching <option>, and the
    # browser would fall back to the blank "Shared / Legacy" choice — silently
    # stripping the archived programme's link on an otherwise-unrelated edit.
    # Union it back in (and label it non-active in the template) so a no-op
    # resubmit round-trips correctly.
    programmes = list_active_programmes()
    if session_obj.programme_id and session_obj.programme_id not in {p.id for p in programmes}:
        programmes = programmes + [session_obj.programme]
    if request.method == 'GET':
        return render_template(
            'admin/session_form.html', session=session_obj, programmes=programmes,
            periods=list_periods(session_id), holidays=list_holidays(session_id),
        )

    name = request.form.get('name', '').strip()
    start_date = request.form.get('start_date') or None
    end_date = request.form.get('end_date') or None
    programme_id = request.form.get('programme_id', type=int) or None
    if not name:
        flash('Session name is required.')
        return render_template('admin/session_form.html', session=session_obj, form=request.form, programmes=programmes)
    if not is_session_name_unique(name, programme_id, exclude_id=session_id):
        flash(f'A session named "{name}" already exists for this programme.')
        return render_template('admin/session_form.html', session=session_obj, form=request.form, programmes=programmes)

    from datetime import date
    start_date = date.fromisoformat(start_date) if start_date else None
    end_date = date.fromisoformat(end_date) if end_date else None

    update_session(session_id, name, start_date, end_date, programme_id=programme_id)
    log_admin_action(current_user, 'session_updated', target_type='academic_session', target_id=session_id,
                      details=f'name={name} programme_id={programme_id}', ip_address=request.remote_addr)
    flash(f'Session "{name}" updated.')
    return redirect(url_for('admin_sessions'))


@app.route('/admin/sessions/<int:session_id>/archive', methods=['POST'])
@permission_required('sessions.manage')
def admin_session_archive(session_id):
    session_obj, error = archive_session(session_id)
    if error:
        flash(error)
    else:
        log_admin_action(current_user, 'session_archived', target_type='academic_session', target_id=session_id,
                          ip_address=request.remote_addr)
        flash(f'Session "{session_obj.name}" archived.')
    return redirect(url_for('admin_sessions'))


@app.route('/admin/sessions/<int:session_id>/clone', methods=['POST'])
@permission_required('sessions.manage')
def admin_session_clone(session_id):
    source_session = get_session(session_id)
    new_name = request.form.get('new_name', '').strip()
    start_date = request.form.get('start_date') or None
    end_date = request.form.get('end_date') or None
    if not new_name:
        flash('New session name is required to clone.')
        return redirect(url_for('admin_sessions'))
    if not is_session_name_unique(new_name, source_session.programme_id):
        flash(f'A session named "{new_name}" already exists for this programme.')
        return redirect(url_for('admin_sessions'))

    from datetime import date
    start_date = date.fromisoformat(start_date) if start_date else None
    end_date = date.fromisoformat(end_date) if end_date else None

    new_session = clone_session(session_id, new_name, start_date, end_date)
    log_admin_action(current_user, 'session_cloned', target_type='academic_session', target_id=new_session.id,
                      details=f'cloned_from={session_id}', ip_address=request.remote_addr)
    flash(f'Cloned into new session "{new_name}".')
    return redirect(url_for('admin_session_edit', session_id=new_session.id))


@app.route('/admin/students/import/preview', methods=['POST'])
@permission_required('students.manage')
def admin_students_import_preview():
    file_storage = request.files.get('file')
    summary, parse_error = preview_students_csv(file_storage)
    if parse_error:
        return jsonify({'success': False, 'message': parse_error}), 400
    return jsonify({'success': True, **summary})


@app.route('/admin/students/import', methods=['GET', 'POST'])
@permission_required('students.manage')
def admin_students_import():
    if request.method == 'GET':
        return render_template('admin/student_import.html')

    file_storage = request.files.get('file')
    job = import_students_csv(file_storage, current_user)
    log_admin_action(
        current_user, 'student_import_completed', target_type='student_import_job', target_id=job.id,
        details=f'created={job.created_count} updated={job.updated_count} skipped={job.skipped_count} '
                f'duplicates={job.duplicate_count} errors={job.error_count}',
        ip_address=request.remote_addr,
    )
    return redirect(url_for('admin_student_import_report', job_id=job.id))


@app.route('/admin/students/import/<int:job_id>')
@permission_required('students.manage')
def admin_student_import_report(job_id):
    job = StudentImportJob.query.get_or_404(job_id)
    return render_template('admin/student_import_report.html', job=job)


@app.route('/admin/students/import/admission-portal')
@permission_required('students.manage')
def admin_student_admission_portal():
    return render_template('admin/coming_soon.html', feature_name='Admission Portal Import')


@app.route('/admin/students')
@permission_required('students.manage')
def admin_students():
    return render_template(
        'admin/students.html', departments=list_active_departments(), programmes=list_active_programmes(),
    )


@app.route('/admin/students/data')
@permission_required('students.manage')
def admin_students_data():
    search = request.args.get('search', '').strip() or None
    department_id = request.args.get('department_id', type=int)
    programme_id = request.args.get('programme_id', type=int)
    level = request.args.get('level', '').strip() or None
    semester = request.args.get('semester', '').strip() or None
    status = request.args.get('status', '').strip() or None
    enrolled_from = request.args.get('enrolled_from') or None
    enrolled_to = request.args.get('enrolled_to') or None
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'name')

    result = list_students(
        search=search, department_id=department_id, programme_id=programme_id, level=level, semester=semester,
        status=status, enrolled_from=enrolled_from, enrolled_to=enrolled_to, page=page, sort=sort,
    )
    return jsonify({
        'success': True,
        'students': [{
            'id': s.id, 'reg_no': s.reg_no, 'name': s.name,
            'department': s.department or '—', 'programme': s.course or '—',
            'level': s.level or '—', 'semester': s.semester or '—', 'status': s.account_status,
            'profile_picture_url': url_for('static', filename=s.profile_picture) if s.profile_picture else None,
        } for s in result['items']],
        'total': result['total'], 'page': result['page'], 'per_page': result['per_page'],
    })


@app.route('/admin/students/<int:student_id>')
@permission_required('students.manage')
def admin_student_profile(student_id):
    profile = get_student_profile(student_id)
    can_override_onboarding = has_permission(current_user, 'onboarding.override')
    return render_template('admin/student_profile.html', can_override_onboarding=can_override_onboarding, **profile)


@app.route('/admin/students/new', methods=['GET', 'POST'])
@permission_required('students.manage')
def admin_student_new():
    departments = list_active_departments()
    programmes = list_active_programmes()
    if request.method == 'GET':
        return render_template('admin/student_form.html', student=None, departments=departments, programmes=programmes)

    from datetime import date

    reg_no = request.form.get('reg_no', '').strip()
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    if not reg_no or not name:
        flash('Registration number and name are required.')
        return render_template('admin/student_form.html', student=None, departments=departments, programmes=programmes, form=request.form)
    if User.query.filter_by(reg_no=reg_no).first():
        flash(f'A student with registration number "{reg_no}" already exists.')
        return render_template('admin/student_form.html', student=None, departments=departments, programmes=programmes, form=request.form)
    if email and User.query.filter_by(email=email).first():
        flash(f'A student with email "{email}" already exists.')
        return render_template('admin/student_form.html', student=None, departments=departments, programmes=programmes, form=request.form)

    programme_id = request.form.get('programme_id', type=int)
    level = request.form.get('level', '').strip()
    if programme_id and level:
        programme = Programme.query.get(programme_id)
        valid_levels = valid_levels_for_programme(programme)
        if valid_levels is not None and level not in valid_levels:
            flash(f'"{level}" is not a valid level for {programme.name} (expected one of: {", ".join(valid_levels)}).')
            return render_template('admin/student_form.html', student=None, departments=departments, programmes=programmes, form=request.form)

    dob_raw = request.form.get('dob') or None
    student, temp_password = create_student(
        reg_no=reg_no, name=name,
        email=email, phone=request.form.get('phone', '').strip(),
        department_id=request.form.get('department_id', type=int), programme_id=programme_id,
        level=level, semester=request.form.get('semester', '').strip(),
        session=request.form.get('session', '').strip(),
        nationality=request.form.get('nationality', '').strip(), state=request.form.get('state', '').strip(),
        lga=request.form.get('lga', '').strip(), dob=date.fromisoformat(dob_raw) if dob_raw else None,
        gender=request.form.get('gender', '').strip(), student_type=request.form.get('student_type', '').strip(),
    )
    log_admin_action(current_user, 'student_created', target_type='user', target_id=student.id,
                      details=f'reg_no={reg_no}', ip_address=request.remote_addr)

    if student.email:
        try:
            msg = Message('Welcome to the Student Portal — Complete Your Onboarding', recipients=[student.email])
            msg.body = (
                f'Hello {student.name},\n\n'
                'An administrator has created your Student Portal account. Use the credentials below to log in '
                'and complete your onboarding:\n\n'
                f'Registration Number: {student.reg_no}\n'
                f'Temporary Password: {temp_password}\n\n'
                'You will be asked to set a new password and complete your profile on first login.'
            )
            mail.send(msg)
        except Exception:
            app.logger.warning('Failed to send onboarding email to %s', student.email)

    flash(f'Student "{name}" ({reg_no}) created. Temporary password: {temp_password}')
    return redirect(url_for('admin_student_profile', student_id=student.id))


@app.route('/admin/students/<int:student_id>/registration/add-course', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_add_course(student_id):
    student = get_student(student_id)
    context = get_student_profile(student_id)['registration_context']
    period, student_registration = context['period'], context['student_registration']
    reason = request.form.get('reason', '').strip()
    course_id = request.form.get('course_id', type=int)
    override_capacity = request.form.get('override_capacity') == 'on'

    if period is None or student_registration is None:
        flash('This student has no active registration to add a course to.')
        return redirect(url_for('admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    try:
        admin_add_course(student, period, student_registration, course_id, current_user, reason, override_capacity=override_capacity)
    except RegistrationError as e:
        flash(str(e))
        return redirect(url_for('admin_student_profile', student_id=student_id))

    log_admin_action(current_user, 'course_added_by_admin', target_type='student_registration', target_id=student_registration.id,
                      details=f'course_id={course_id} override_capacity={override_capacity} reason={reason}', ip_address=request.remote_addr)
    flash('Course added to student\'s registration.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/registration/drop-course', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_drop_course(student_id):
    student = get_student(student_id)
    context = get_student_profile(student_id)['registration_context']
    period, student_registration = context['period'], context['student_registration']
    reason = request.form.get('reason', '').strip()
    course_id = request.form.get('course_id', type=int)

    if period is None or student_registration is None:
        flash('This student has no active registration to drop a course from.')
        return redirect(url_for('admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    try:
        admin_drop_course(student, period, student_registration, course_id, current_user, reason)
    except RegistrationError as e:
        flash(str(e))
        return redirect(url_for('admin_student_profile', student_id=student_id))

    log_admin_action(current_user, 'course_removed_by_admin', target_type='student_registration', target_id=student_registration.id,
                      details=f'course_id={course_id} reason={reason}', ip_address=request.remote_addr)
    flash('Course removed from student\'s registration.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/registration/lock', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_lock(student_id):
    context = get_student_profile(student_id)['registration_context']
    student_registration = context['student_registration']
    reason = request.form.get('reason', '').strip()
    locked = request.form.get('locked') == 'true'

    if student_registration is None:
        flash('This student has no active registration.')
        return redirect(url_for('admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    set_registration_lock(student_registration, current_user, locked, reason)
    log_admin_action(current_user, 'registration_locked' if locked else 'registration_unlocked',
                      target_type='student_registration', target_id=student_registration.id,
                      details=reason, ip_address=request.remote_addr)
    flash(f'Registration {"locked" if locked else "unlocked"}.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/registration/extend-deadline', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_extend_deadline(student_id):
    from datetime import datetime

    context = get_student_profile(student_id)['registration_context']
    student_registration = context['student_registration']
    reason = request.form.get('reason', '').strip()
    new_deadline_raw = request.form.get('new_deadline', '')

    if student_registration is None:
        flash('This student has no active registration.')
        return redirect(url_for('admin_student_profile', student_id=student_id))
    if not reason or not new_deadline_raw:
        flash('A reason and a new deadline are required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    try:
        new_deadline = datetime.fromisoformat(new_deadline_raw)
    except ValueError:
        flash('Invalid deadline format.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    extend_deadline(student_registration, current_user, new_deadline, reason)
    log_admin_action(current_user, 'registration_deadline_extended', target_type='student_registration',
                      target_id=student_registration.id, details=f'new_deadline={new_deadline_raw} reason={reason}',
                      ip_address=request.remote_addr)
    flash('Deadline extended for this student.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/registration/reopen', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_reopen(student_id):
    context = get_student_profile(student_id)['registration_context']
    student_registration = context['student_registration']
    reason = request.form.get('reason', '').strip()

    if student_registration is None:
        flash('This student has no active registration.')
        return redirect(url_for('admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    reopen_registration(student_registration, current_user, reason)
    log_admin_action(current_user, 'registration_reopened', target_type='student_registration',
                      target_id=student_registration.id, details=reason, ip_address=request.remote_addr)
    flash('Registration reopened — the student can resume course selection.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/registration/approve-exception', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_approve_exception(student_id):
    context = get_student_profile(student_id)['registration_context']
    student_registration = context['student_registration']
    reason = request.form.get('reason', '').strip()

    if student_registration is None:
        flash('This student has no active registration.')
        return redirect(url_for('admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    approve_exception(student_registration, current_user, reason)
    log_admin_action(current_user, 'registration_exception_approved', target_type='student_registration',
                      target_id=student_registration.id, details=reason, ip_address=request.remote_addr)
    flash('Exception recorded for this student\'s registration.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/onboarding/reset', methods=['POST'])
@permission_required('students.manage')
def admin_student_onboarding_reset(student_id):
    student = get_student(student_id)
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    reset_onboarding(student)
    log_admin_action(current_user, 'onboarding_reset', target_type='user', target_id=student_id,
                      details=reason, ip_address=request.remote_addr)
    flash(f'Onboarding reset for {student.name}.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/onboarding/verify-email', methods=['POST'])
@permission_required('students.manage')
def admin_student_onboarding_verify_email(student_id):
    student = get_student(student_id)
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    manually_verify_email(student)
    log_admin_action(current_user, 'email_manually_verified', target_type='user', target_id=student_id,
                      details=reason, ip_address=request.remote_addr)
    flash(f'Email manually verified for {student.name}.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/onboarding/mark-complete', methods=['POST'])
@permission_required('onboarding.override')
def admin_student_onboarding_mark_complete(student_id):
    student = get_student(student_id)
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    mark_onboarding_complete(student)
    log_admin_action(current_user, 'onboarding_marked_complete', target_type='user', target_id=student_id,
                      details=reason, ip_address=request.remote_addr)
    flash(f'Onboarding marked complete for {student.name}.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/edit', methods=['GET', 'POST'])
@permission_required('students.manage')
def admin_student_edit(student_id):
    student = get_student(student_id)
    departments = list_active_departments()
    programmes = list_active_programmes()
    if request.method == 'GET':
        return render_template('admin/student_form.html', student=student, departments=departments, programmes=programmes)

    from datetime import date

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip() or None
    if not name:
        flash('Name is required.')
        return render_template('admin/student_form.html', student=student, departments=departments, programmes=programmes, form=request.form)
    if email and User.query.filter(User.email == email, User.id != student_id).first():
        flash(f'A student with email "{email}" already exists.')
        return render_template('admin/student_form.html', student=student, departments=departments, programmes=programmes, form=request.form)

    programme_id = request.form.get('programme_id', type=int)
    level = request.form.get('level', '').strip() or None
    if programme_id and level:
        programme = Programme.query.get(programme_id)
        valid_levels = valid_levels_for_programme(programme)
        if valid_levels is not None and level not in valid_levels:
            flash(f'"{level}" is not a valid level for {programme.name} (expected one of: {", ".join(valid_levels)}).')
            return render_template('admin/student_form.html', student=student, departments=departments, programmes=programmes, form=request.form)

    dob_raw = request.form.get('dob') or None
    update_student(
        student_id, name=name,
        email=email, phone=request.form.get('phone', '').strip() or None,
        department_id=request.form.get('department_id', type=int), programme_id=programme_id,
        level=level, semester=request.form.get('semester', '').strip() or None,
        session=request.form.get('session', '').strip() or None,
        nationality=request.form.get('nationality', '').strip() or None, state=request.form.get('state', '').strip() or None,
        lga=request.form.get('lga', '').strip() or None, dob=date.fromisoformat(dob_raw) if dob_raw else None,
        gender=request.form.get('gender', '').strip() or None, student_type=request.form.get('student_type', '').strip() or None,
    )
    log_admin_action(current_user, 'student_updated', target_type='user', target_id=student_id,
                      details=f'reg_no={student.reg_no}', ip_address=request.remote_addr)
    flash(f'Student "{name}" updated.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/activate', methods=['POST'])
@permission_required('students.manage')
def admin_student_activate(student_id):
    set_account_status(student_id, 'active')
    log_admin_action(current_user, 'student_status_changed', target_type='user', target_id=student_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Student account activated.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/suspend', methods=['POST'])
@permission_required('students.manage')
def admin_student_suspend(student_id):
    set_account_status(student_id, 'suspended')
    log_admin_action(current_user, 'student_status_changed', target_type='user', target_id=student_id,
                      details='status=suspended', ip_address=request.remote_addr)
    flash('Student account suspended.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/deactivate', methods=['POST'])
@permission_required('students.manage')
def admin_student_deactivate(student_id):
    set_account_status(student_id, 'deactivated')
    log_admin_action(current_user, 'student_status_changed', target_type='user', target_id=student_id,
                      details='status=deactivated', ip_address=request.remote_addr)
    flash('Student account deactivated.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/reset-password', methods=['POST'])
@permission_required('students.manage')
def admin_student_reset_password(student_id):
    temp_password = reset_student_password(student_id)
    log_admin_action(current_user, 'student_password_reset', target_type='user', target_id=student_id,
                      ip_address=request.remote_addr)
    flash(f'Password reset. Temporary password: {temp_password}')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/<int:student_id>/resend-verification', methods=['POST'])
@permission_required('students.manage')
def admin_student_resend_verification(student_id):
    ok, error = resend_verification(student_id)
    if not ok:
        flash(error)
        return redirect(url_for('admin_student_profile', student_id=student_id))

    student = get_student(student_id)
    try:
        msg = Message('Complete Your Email Verification', recipients=[student.email])
        msg.body = (
            f'Hello {student.name},\n\n'
            'An administrator noticed your email address on the Student Portal hasn\'t been verified yet. '
            'Please log in and complete your onboarding to verify it.\n\n'
            'If you did not request this, you can safely ignore this email.'
        )
        mail.send(msg)
    except Exception:
        app.logger.warning('Failed to send verification reminder to %s', student.email)

    create_notification(
        student, 'Verify your email', 'Please log in and complete your onboarding to verify your email address.',
        category='profile', priority='medium',
    )
    log_admin_action(current_user, 'student_verification_resent', target_type='user', target_id=student_id,
                      ip_address=request.remote_addr)
    flash('Verification reminder sent.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@app.route('/admin/students/bulk-status', methods=['POST'])
@permission_required('students.manage')
def admin_students_bulk_status():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    student_ids = data.get('student_ids', [])
    status = data.get('status')
    if not student_ids or status not in ('active', 'suspended', 'deactivated'):
        return jsonify({'success': False, 'message': 'student_ids and a valid status are required.'}), 400

    count = bulk_set_status(student_ids, status)
    log_admin_action(current_user, 'student_bulk_status_changed', target_type='user', target_id=None,
                      details=f'status={status} count={count} ids={student_ids}', ip_address=request.remote_addr)
    return jsonify({'success': True, 'message': f'{count} student(s) updated to {status}.', 'count': count})


@app.route('/admin/students/bulk-reset-password', methods=['POST'])
@permission_required('students.manage')
def admin_students_bulk_reset_password():
    data = request.get_json()
    if not data or not data.get('student_ids'):
        return jsonify({'success': False, 'message': 'student_ids is required.'}), 400

    student_ids = data['student_ids']
    results = bulk_reset_password(student_ids)
    log_admin_action(current_user, 'student_bulk_password_reset', target_type='user', target_id=None,
                      details=f'count={len(results)} ids={student_ids}', ip_address=request.remote_addr)
    return jsonify({'success': True, 'message': f'{len(results)} password(s) reset.', 'results': results})


@app.route('/admin/students/bulk-resend-email', methods=['POST'])
@permission_required('students.manage')
def admin_students_bulk_resend_email():
    data = request.get_json()
    if not data or not data.get('student_ids'):
        return jsonify({'success': False, 'message': 'student_ids is required.'}), 400

    student_ids = data['student_ids']
    sent = skipped = 0
    for student_id in student_ids:
        student = User.query.get(student_id)
        if student is None:
            skipped += 1
            continue
        ok, _ = resend_verification(student_id)
        if not ok:
            skipped += 1
            continue
        try:
            msg = Message('Complete Your Email Verification', recipients=[student.email])
            msg.body = (
                f'Hello {student.name},\n\n'
                'An administrator noticed your email address on the Student Portal hasn\'t been verified yet. '
                'Please log in and complete your onboarding to verify it.\n\n'
                'If you did not request this, you can safely ignore this email.'
            )
            mail.send(msg)
            sent += 1
        except Exception:
            app.logger.warning('Failed to send verification reminder to %s', student.email)
            skipped += 1
        create_notification(
            student, 'Verify your email', 'Please log in and complete your onboarding to verify your email address.',
            category='profile', priority='medium',
        )

    log_admin_action(current_user, 'student_bulk_verification_resent', target_type='user', target_id=None,
                      details=f'sent={sent} skipped={skipped} ids={student_ids}', ip_address=request.remote_addr)
    return jsonify({'success': True, 'message': f'{sent} email(s) sent, {skipped} skipped (no email on file).'})


@app.route('/admin/students/bulk-assign-department', methods=['POST'])
@permission_required('students.manage')
def admin_students_bulk_assign_department():
    data = request.get_json()
    if not data or not data.get('student_ids') or not data.get('department_id'):
        return jsonify({'success': False, 'message': 'student_ids and department_id are required.'}), 400

    student_ids = data['student_ids']
    count = bulk_assign_department(student_ids, data['department_id'])
    log_admin_action(current_user, 'student_bulk_department_assigned', target_type='user', target_id=None,
                      details=f'department_id={data["department_id"]} count={count} ids={student_ids}',
                      ip_address=request.remote_addr)
    return jsonify({'success': True, 'message': f'{count} student(s) assigned.', 'count': count})


@app.route('/admin/students/bulk-assign-programme', methods=['POST'])
@permission_required('students.manage')
def admin_students_bulk_assign_programme():
    data = request.get_json()
    if not data or not data.get('student_ids') or not data.get('programme_id'):
        return jsonify({'success': False, 'message': 'student_ids and programme_id are required.'}), 400

    student_ids = data['student_ids']
    count = bulk_assign_programme(student_ids, data['programme_id'])
    log_admin_action(current_user, 'student_bulk_programme_assigned', target_type='user', target_id=None,
                      details=f'programme_id={data["programme_id"]} count={count} ids={student_ids}',
                      ip_address=request.remote_addr)
    return jsonify({'success': True, 'message': f'{count} student(s) assigned.', 'count': count})


@app.route('/admin/course-catalog')
@permission_required('courses.manage')
def admin_course_catalog():
    search = request.args.get('search', '').strip() or None
    status = request.args.get('status', '').strip() or None
    page = request.args.get('page', 1, type=int)
    result = list_master_courses(search=search, status=status, page=page)
    return render_template(
        'admin/course_catalog.html', result=result, search=search or '', status=status or '',
    )


@app.route('/admin/course-catalog/new', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_catalog_new():
    if request.method == 'GET':
        return render_template('admin/course_catalog_form.html', course=None)

    code = request.form.get('code', '').strip().upper()
    title = request.form.get('title', '').strip()
    credits = request.form.get('credits', type=int)
    course_type = request.form.get('course_type', '').strip()
    description = request.form.get('description', '').strip()

    errors = []
    if not code or not title or not credits or not course_type:
        errors.append('Code, title, credits, and course type are required.')
    elif not is_course_catalog_code_unique(code):
        errors.append(f'Course code "{code}" already exists in the catalog.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/course_catalog_form.html', course=None, form=request.form)

    course = create_master_course(code, title, credits, course_type, description=description)
    log_admin_action(current_user, 'course_catalog_created', target_type='course', target_id=course.id,
                      details=f'code={code}', ip_address=request.remote_addr)
    flash(f'Course "{code}" added to the catalog.')
    return redirect(url_for('admin_course_catalog_detail', course_id=course.id))


@app.route('/admin/course-catalog/<int:course_id>')
@permission_required('courses.manage')
def admin_course_catalog_detail(course_id):
    detail = get_master_course_detail(course_id)
    other_courses = list_master_courses_for_picker(exclude_id=course_id)
    return render_template('admin/course_catalog.html', detail=detail, result=None, other_courses=other_courses)


@app.route('/admin/course-catalog/<int:course_id>/edit', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_catalog_edit(course_id):
    course = get_master_course(course_id)
    if request.method == 'GET':
        return render_template('admin/course_catalog_form.html', course=course)

    code = request.form.get('code', '').strip().upper()
    title = request.form.get('title', '').strip()
    credits = request.form.get('credits', type=int)
    course_type = request.form.get('course_type', '').strip()
    description = request.form.get('description', '').strip()

    errors = []
    if not code or not title or not credits or not course_type:
        errors.append('Code, title, credits, and course type are required.')
    elif not is_course_catalog_code_unique(code, exclude_id=course_id):
        errors.append(f'Course code "{code}" already exists in the catalog.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/course_catalog_form.html', course=course, form=request.form)

    update_master_course(course_id, code, title, credits, course_type, description=description)
    log_admin_action(current_user, 'course_catalog_updated', target_type='course', target_id=course_id,
                      details=f'code={code}', ip_address=request.remote_addr)
    flash(f'Course "{code}" updated.')
    return redirect(url_for('admin_course_catalog_detail', course_id=course_id))


@app.route('/admin/course-catalog/<int:course_id>/prerequisites', methods=['POST'])
@permission_required('courses.manage')
def admin_course_catalog_prerequisites(course_id):
    prereq_ids = request.form.getlist('prerequisite_ids', type=int)
    set_prerequisites(course_id, prereq_ids)
    log_admin_action(current_user, 'course_catalog_prerequisites_updated', target_type='course', target_id=course_id,
                      details=f'count={len(prereq_ids)}', ip_address=request.remote_addr)
    flash('Prerequisites updated.')
    return redirect(url_for('admin_course_catalog_detail', course_id=course_id))


@app.route('/admin/course-catalog/<int:course_id>/corequisites', methods=['POST'])
@permission_required('courses.manage')
def admin_course_catalog_corequisites(course_id):
    coreq_ids = request.form.getlist('corequisite_ids', type=int)
    set_corequisites(course_id, coreq_ids)
    log_admin_action(current_user, 'course_catalog_corequisites_updated', target_type='course', target_id=course_id,
                      details=f'count={len(coreq_ids)}', ip_address=request.remote_addr)
    flash('Corequisites updated.')
    return redirect(url_for('admin_course_catalog_detail', course_id=course_id))


@app.route('/admin/course-catalog/<int:course_id>/activate', methods=['POST'])
@permission_required('courses.manage')
def admin_course_catalog_activate(course_id):
    set_master_course_status(course_id, 'active')
    log_admin_action(current_user, 'course_catalog_status_changed', target_type='course', target_id=course_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Course activated.')
    return redirect(url_for('admin_course_catalog_detail', course_id=course_id))


@app.route('/admin/course-catalog/<int:course_id>/archive', methods=['POST'])
@permission_required('courses.manage')
def admin_course_catalog_archive(course_id):
    set_master_course_status(course_id, 'archived')
    log_admin_action(current_user, 'course_catalog_status_changed', target_type='course', target_id=course_id,
                      details='status=archived', ip_address=request.remote_addr)
    flash('Course archived.')
    return redirect(url_for('admin_course_catalog_detail', course_id=course_id))


@app.route('/admin/courses')
@permission_required('courses.manage')
def admin_courses():
    return render_template('admin/courses.html', departments=list_active_departments(), semesters=list_semesters())


@app.route('/admin/courses/data')
@permission_required('courses.manage')
def admin_courses_data():
    search = request.args.get('search', '').strip() or None
    department_id = request.args.get('department_id', type=int)
    level = request.args.get('level', '').strip() or None
    semester_id = request.args.get('semester_id', type=int)
    min_credits = request.args.get('min_credits', type=int)
    max_credits = request.args.get('max_credits', type=int)
    status = request.args.get('status', '').strip() or None
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'code')

    result = list_courses(
        search=search, department_id=department_id, level=level, semester_id=semester_id,
        min_credits=min_credits, max_credits=max_credits, status=status, page=page, sort=sort,
    )
    def course_json(c):
        enrolled = get_enrollment_count(c.id)
        remaining = (c.max_capacity - enrolled) if c.max_capacity is not None else None
        return {
            'id': c.id, 'code': c.code, 'title': c.title, 'department': c.department,
            'level': c.level or '—', 'semester': c.semester.name, 'credits': c.credits, 'status': c.status,
            'enrolled': enrolled, 'max_capacity': c.max_capacity if c.max_capacity is not None else '—',
            'remaining': remaining if remaining is not None else '—',
        }

    return jsonify({
        'success': True,
        'courses': [course_json(c) for c in result['items']],
        'total': result['total'], 'page': result['page'], 'per_page': result['per_page'],
    })


@app.route('/admin/courses/new', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_new():
    departments = list_active_departments()
    sessions = list_sessions()
    semesters = list_semesters()
    master_courses = list_master_courses_for_picker()
    if request.method == 'GET':
        return render_template('admin/course_form.html', course=None, departments=departments, sessions=sessions, semesters=semesters, master_courses=master_courses)

    master_course_id = request.form.get('master_course_id', type=int)
    department_id = request.form.get('department_id', type=int)
    max_capacity = request.form.get('max_capacity', type=int)
    level = request.form.get('level', '').strip()
    academic_session_id = request.form.get('academic_session_id', type=int)
    semester_id = request.form.get('semester_id', type=int)
    instructor = request.form.get('instructor', '').strip()
    schedule = request.form.get('schedule', '').strip()

    errors = []
    if not master_course_id or not department_id or not academic_session_id or not semester_id:
        errors.append('Master course, department, session, and semester are required.')
    elif master_course_id not in {mc.id for mc in master_courses}:
        # Backstop against a crafted/stale request posting a master_course_id
        # outside what's actually offered — don't just trust whatever the
        # client posts even if the template ever regresses. See the matching
        # comment in admin_course_edit for the fuller rationale (that route
        # additionally protects a pre-existing offering's link).
        errors.append('Selected master course is not valid.')
    else:
        master = get_master_course(master_course_id)
        if not is_course_code_unique(master.code, academic_session_id, semester_id):
            errors.append(f'"{master.code}" already has an offering for that session/semester.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/course_form.html', course=None, departments=departments, sessions=sessions, semesters=semesters, master_courses=master_courses, form=request.form)

    offering = create_course(
        master_course_id, department_id, level, academic_session_id, semester_id,
        instructor=instructor, schedule=schedule, max_capacity=max_capacity,
    )
    log_admin_action(current_user, 'course_created', target_type='course', target_id=offering.id,
                      details=f'code={offering.code} master_course_id={master_course_id}', ip_address=request.remote_addr)
    flash(f'Course offering "{offering.code}" created.')
    return redirect(url_for('admin_course_detail', course_id=offering.id))


@app.route('/admin/courses/<int:course_id>')
@permission_required('courses.manage')
def admin_course_detail(course_id):
    detail = get_course_detail(course_id)
    enrolled = get_enrollment_count(course_id)
    return render_template('admin/course_detail.html', enrolled=enrolled, **detail)


@app.route('/admin/courses/<int:course_id>/assessment', methods=['POST'])
@permission_required('courses.manage')
def admin_course_assessment(course_id):
    names = request.form.getlist('component_name')
    weights = request.form.getlist('component_weight')
    components = []
    for name, weight in zip(names, weights):
        name = name.strip()
        if name and weight:
            try:
                components.append({'name': name, 'weight_percent': int(weight)})
            except ValueError:
                continue

    set_assessment_components(course_id, components)
    total_weight = sum(c['weight_percent'] for c in components)
    if components and total_weight != 100:
        flash(f'Assessment components saved, but weights total {total_weight}% (expected 100%) — double-check before relying on this.')
    else:
        flash('Assessment components updated.')
    log_admin_action(current_user, 'course_assessment_updated', target_type='course', target_id=course_id,
                      details=f'count={len(components)} total_weight={total_weight}', ip_address=request.remote_addr)
    return redirect(url_for('admin_course_detail', course_id=course_id))


@app.route('/admin/courses/<int:course_id>/edit', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_edit(course_id):
    offering = get_course(course_id)
    departments = list_active_departments()
    sessions = list_sessions()
    semesters = list_semesters()
    # The offering's currently-linked master Course can be archived at any
    # time via the Course Catalog module, dropping it out of the plain
    # active-only picker. If we didn't union it back in, an admin who edits
    # this offering without touching the Master Course field would have the
    # browser silently default to selecting the *first* option — silently
    # re-linking (and re-mirroring code/title/credits/course_type/description
    # from) an unrelated master on an otherwise-unrelated edit. Union it back
    # in (labeled distinctly in the template) so a no-op resubmit round-trips
    # correctly. Same pattern as the period-edit Semester-dropdown fix.
    master_courses = list_master_courses_for_picker(include_id=offering.course_id)
    if request.method == 'GET':
        return render_template('admin/course_form.html', course=offering, departments=departments, sessions=sessions, semesters=semesters, master_courses=master_courses)

    master_course_id = request.form.get('master_course_id', type=int)
    department_id = request.form.get('department_id', type=int)
    max_capacity = request.form.get('max_capacity', type=int)
    level = request.form.get('level', '').strip()
    academic_session_id = request.form.get('academic_session_id', type=int)
    semester_id = request.form.get('semester_id', type=int)
    instructor = request.form.get('instructor', '').strip()
    schedule = request.form.get('schedule', '').strip()

    errors = []
    if not master_course_id or not department_id or not academic_session_id or not semester_id:
        errors.append('Master course, department, session, and semester are required.')
    elif master_course_id not in {mc.id for mc in master_courses}:
        # Backstop against a crafted/stale request posting a master_course_id
        # outside what's actually offered (the active set, plus the
        # offering's own current master if it was unioned back in above) —
        # don't just trust whatever the client posts even if the template
        # ever regresses. Same shape as the period-edit Semester backstop.
        errors.append('Selected master course is not valid.')
    else:
        master = get_master_course(master_course_id)
        if not is_course_code_unique(master.code, academic_session_id, semester_id, exclude_id=course_id):
            errors.append(f'"{master.code}" already has an offering for that session/semester.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/course_form.html', course=offering, departments=departments, sessions=sessions, semesters=semesters, master_courses=master_courses, form=request.form)

    update_course(
        course_id, master_course_id=master_course_id, department_id=department_id,
        level=level or None, academic_session_id=academic_session_id, semester_id=semester_id,
        instructor=instructor or None, schedule=schedule or None, max_capacity=max_capacity,
    )
    log_admin_action(current_user, 'course_updated', target_type='course', target_id=course_id,
                      details=f'master_course_id={master_course_id}', ip_address=request.remote_addr)
    flash('Course offering updated.')
    return redirect(url_for('admin_course_detail', course_id=course_id))


@app.route('/admin/courses/<int:course_id>/activate', methods=['POST'])
@permission_required('courses.manage')
def admin_course_activate(course_id):
    set_course_status(course_id, 'active')
    log_admin_action(current_user, 'course_status_changed', target_type='course', target_id=course_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Course activated.')
    return redirect(url_for('admin_course_detail', course_id=course_id))


@app.route('/admin/courses/<int:course_id>/deactivate', methods=['POST'])
@permission_required('courses.manage')
def admin_course_deactivate(course_id):
    set_course_status(course_id, 'inactive')
    log_admin_action(current_user, 'course_status_changed', target_type='course', target_id=course_id,
                      details='status=inactive', ip_address=request.remote_addr)
    flash('Course deactivated for the current offering.')
    return redirect(url_for('admin_course_detail', course_id=course_id))


@app.route('/admin/courses/<int:course_id>/archive', methods=['POST'])
@permission_required('courses.manage')
def admin_course_archive(course_id):
    set_course_status(course_id, 'archived')
    log_admin_action(current_user, 'course_status_changed', target_type='course', target_id=course_id,
                      details='status=archived', ip_address=request.remote_addr)
    flash('Course archived.')
    return redirect(url_for('admin_course_detail', course_id=course_id))


@app.route('/admin/courses/import/preview', methods=['POST'])
@permission_required('courses.manage')
def admin_course_import_preview():
    file_storage = request.files.get('file')
    summary, parse_error = preview_courses_csv(file_storage)
    if parse_error:
        return jsonify({'success': False, 'message': parse_error}), 400
    return jsonify({'success': True, **summary})


@app.route('/admin/courses/import', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_import():
    if request.method == 'GET':
        return render_template('admin/course_import.html', sessions=list_sessions())

    academic_session_id = request.form.get('academic_session_id', type=int)
    file_storage = request.files.get('file')
    if not academic_session_id:
        flash('Please choose an academic session.')
        return redirect(url_for('admin_course_import'))

    job = import_courses_csv(file_storage, current_user, academic_session_id)
    log_admin_action(
        current_user, 'course_import_completed', target_type='course_import_job', target_id=job.id,
        details=f'created={job.created_count} updated={job.updated_count} skipped={job.skipped_count} '
                f'duplicates={job.duplicate_count} errors={job.error_count}',
        ip_address=request.remote_addr,
    )
    return redirect(url_for('admin_course_import_report', job_id=job.id))


@app.route('/admin/courses/import/<int:job_id>')
@permission_required('courses.manage')
def admin_course_import_report(job_id):
    job = CourseImportJob.query.get_or_404(job_id)
    return render_template('admin/course_import_report.html', job=job)


@app.route('/admin/sessions/<int:session_id>/periods/new', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_period_new(session_id):
    session_obj = get_session(session_id)
    semesters = list_semesters_for_programme(session_obj.programme)
    if request.method == 'GET':
        return render_template('admin/period_form.html', session=session_obj, period=None, semesters=semesters, mismatched_semester_id=None)

    from datetime import datetime

    def parse_dt(value):
        return datetime.fromisoformat(value) if value else None

    semester_id = request.form.get('semester_id', type=int)
    opens_at = parse_dt(request.form.get('opens_at') or None)
    closes_at = parse_dt(request.form.get('closes_at') or None)
    min_credits = request.form.get('min_credits', type=int)
    max_credits = request.form.get('max_credits', type=int)
    registration_fee = request.form.get('registration_fee', type=float) or 0

    errors = validate_credit_range(min_credits, max_credits)
    if not semester_id or not opens_at or not closes_at:
        errors.append('Semester, opens-at, and closes-at are required.')
    elif semester_id not in {s.id for s in semesters}:
        # Backstop against a crafted/stale request posting a semester_id outside
        # what this session's Programme scope actually offers — see the matching
        # comment in admin_period_edit for the full rationale.
        errors.append('Selected semester is not valid for this session\'s programme.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/period_form.html', session=session_obj, period=None, semesters=semesters, form=request.form, mismatched_semester_id=None)

    period = create_period(
        session_id, semester_id, opens_at, closes_at, min_credits, max_credits, registration_fee,
        late_registration_ends_at=parse_dt(request.form.get('late_registration_ends_at') or None),
        late_registration_fee=request.form.get('late_registration_fee', type=float) or None,
        exam_starts_at=parse_dt(request.form.get('exam_starts_at') or None),
        exam_ends_at=parse_dt(request.form.get('exam_ends_at') or None),
        result_release_at=parse_dt(request.form.get('result_release_at') or None),
        add_drop_opens_at=parse_dt(request.form.get('add_drop_opens_at') or None),
        add_drop_closes_at=parse_dt(request.form.get('add_drop_closes_at') or None),
    )
    log_admin_action(current_user, 'registration_period_created', target_type='registration_period', target_id=period.id,
                      details=f'session_id={session_id} semester_id={semester_id}', ip_address=request.remote_addr)
    flash('Registration period created.')
    return redirect(url_for('admin_session_edit', session_id=session_id))


@app.route('/admin/sessions/<int:session_id>/periods/<int:period_id>/edit', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_period_edit(session_id, period_id):
    session_obj = get_session(session_id)
    period = get_period(period_id)
    # A RegistrationPeriod's semester_id can reference a Semester that's no
    # longer in this session's Programme's filtered calendar shape (e.g. the
    # session was scoped to a Programme, or the Programme's
    # uses_semesters/uses_terms flags were toggled, after this period was
    # already created against a different semester). If we dropped it from the
    # dropdown, an admin who edits the period without touching the Semester
    # field would have the browser silently default to selecting the *first*
    # option — silently reassigning the period to a completely different
    # semester on an otherwise-unrelated edit (e.g. date-only change). Union
    # it back in (and label it distinctly in the template) so a no-op resubmit
    # round-trips correctly. Same pattern as c797c91's session-Programme fix.
    semesters = list_semesters_for_programme(session_obj.programme)
    mismatched_semester_id = None
    if period.semester_id not in {s.id for s in semesters}:
        semesters = semesters + [period.semester]
        mismatched_semester_id = period.semester_id
    if request.method == 'GET':
        return render_template('admin/period_form.html', session=session_obj, period=period, semesters=semesters, mismatched_semester_id=mismatched_semester_id)

    from datetime import datetime

    def parse_dt(value):
        return datetime.fromisoformat(value) if value else None

    semester_id = request.form.get('semester_id', type=int)
    opens_at = parse_dt(request.form.get('opens_at') or None)
    closes_at = parse_dt(request.form.get('closes_at') or None)
    min_credits = request.form.get('min_credits', type=int)
    max_credits = request.form.get('max_credits', type=int)
    registration_fee = request.form.get('registration_fee', type=float) or 0

    errors = validate_credit_range(min_credits, max_credits)
    if not semester_id or not opens_at or not closes_at:
        errors.append('Semester, opens-at, and closes-at are required.')
    elif semester_id not in {s.id for s in semesters}:
        # Backstop against a crafted/stale request posting a semester_id outside
        # what's actually offered (the Programme-filtered set, plus the period's
        # own current semester if it was unioned back in above) — don't just
        # trust whatever the client posts even if the template ever regresses.
        errors.append('Selected semester is not valid for this session\'s programme.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/period_form.html', session=session_obj, period=period, semesters=semesters, form=request.form, mismatched_semester_id=mismatched_semester_id)

    update_period(
        period_id, semester_id=semester_id, opens_at=opens_at, closes_at=closes_at,
        min_credits=min_credits, max_credits=max_credits, registration_fee=registration_fee,
        late_registration_ends_at=parse_dt(request.form.get('late_registration_ends_at') or None),
        late_registration_fee=request.form.get('late_registration_fee', type=float) or None,
        exam_starts_at=parse_dt(request.form.get('exam_starts_at') or None),
        exam_ends_at=parse_dt(request.form.get('exam_ends_at') or None),
        result_release_at=parse_dt(request.form.get('result_release_at') or None),
        add_drop_opens_at=parse_dt(request.form.get('add_drop_opens_at') or None),
        add_drop_closes_at=parse_dt(request.form.get('add_drop_closes_at') or None),
    )
    log_admin_action(current_user, 'registration_period_updated', target_type='registration_period', target_id=period_id,
                      ip_address=request.remote_addr)
    flash('Registration period updated.')
    return redirect(url_for('admin_session_edit', session_id=session_id))


@app.route('/admin/sessions/<int:session_id>/periods/<int:period_id>/activate', methods=['POST'])
@permission_required('registration.manage')
def admin_period_activate(session_id, period_id):
    activate_period(period_id)
    log_admin_action(current_user, 'registration_period_activated', target_type='registration_period', target_id=period_id,
                      ip_address=request.remote_addr)
    flash('Registration period activated.')
    return redirect(request.referrer or url_for('admin_sessions'))


@app.route('/admin/sessions/<int:session_id>/holidays', methods=['POST'])
@permission_required('sessions.manage')
def admin_holiday_new(session_id):
    from datetime import date

    name = request.form.get('name', '').strip()
    starts_on = request.form.get('starts_on')
    ends_on = request.form.get('ends_on')
    if not name or not starts_on or not ends_on:
        flash('Holiday name, start date, and end date are required.')
        return redirect(url_for('admin_session_edit', session_id=session_id))

    holiday = create_holiday(session_id, name, date.fromisoformat(starts_on), date.fromisoformat(ends_on))
    log_admin_action(current_user, 'holiday_created', target_type='academic_holiday', target_id=holiday.id,
                      details=f'session_id={session_id} name={name}', ip_address=request.remote_addr)
    flash(f'Holiday "{name}" added.')
    return redirect(url_for('admin_session_edit', session_id=session_id))


@app.route('/admin/fee-structure')
@permission_required('sessions.manage')
def admin_fee_structures():
    session_id = request.args.get('session_id', type=int)
    rows = list_fee_structures(session_id=session_id)
    return render_template(
        'admin/fee_structures.html', rows=rows,
        sessions=list_sessions(), selected_session_id=session_id,
    )


@app.route('/admin/fee-structure/new', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_fee_structure_new():
    sessions = list_sessions()
    session_id = request.args.get('session_id', type=int) or request.form.get('academic_session_id', type=int)
    selected_session = get_session(session_id) if session_id else None
    semesters = list_semesters_for_programme(selected_session.programme) if selected_session else []
    departments = list_active_departments()
    categories = PaymentCategory.query.filter_by(is_active=True).order_by(PaymentCategory.name).all()

    if request.method == 'GET' or selected_session is None:
        return render_template(
            'admin/fee_structure_form.html', row=None, sessions=sessions,
            selected_session=selected_session, semesters=semesters,
            departments=departments, categories=categories,
        )

    semester_id = request.form.get('semester_id', type=int) or None
    department_id = request.form.get('department_id', type=int) or None
    category_id = request.form.get('category_id', type=int)
    amount = request.form.get('amount', type=float)

    if not category_id or amount is None:
        flash('Category and amount are required.')
        return render_template(
            'admin/fee_structure_form.html', row=None, sessions=sessions,
            selected_session=selected_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )
    if not is_fee_structure_scope_unique(selected_session.id, semester_id, department_id, category_id):
        flash('A fee structure row for this exact session/semester/department/category combination already exists.')
        return render_template(
            'admin/fee_structure_form.html', row=None, sessions=sessions,
            selected_session=selected_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )

    row = create_fee_structure(selected_session.id, semester_id, department_id, category_id, amount)
    log_admin_action(current_user, 'fee_structure_created', target_type='fee_structure', target_id=row.id,
                      details=f'session_id={selected_session.id} semester_id={semester_id} department_id={department_id} category_id={category_id} amount={amount}',
                      ip_address=request.remote_addr)
    flash('Fee structure row created.')
    return redirect(url_for('admin_fee_structures', session_id=selected_session.id))


@app.route('/admin/fee-structure/<int:fee_structure_id>/edit', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_fee_structure_edit(fee_structure_id):
    row = get_fee_structure(fee_structure_id)
    semesters = list_semesters_for_programme(row.academic_session.programme)
    departments = list_active_departments()
    categories = PaymentCategory.query.filter_by(is_active=True).order_by(PaymentCategory.name).all()

    if request.method == 'GET':
        return render_template(
            'admin/fee_structure_form.html', row=row, sessions=None,
            selected_session=row.academic_session, semesters=semesters,
            departments=departments, categories=categories,
        )

    semester_id = request.form.get('semester_id', type=int) or None
    department_id = request.form.get('department_id', type=int) or None
    category_id = request.form.get('category_id', type=int)
    amount = request.form.get('amount', type=float)

    if not category_id or amount is None:
        flash('Category and amount are required.')
        return render_template(
            'admin/fee_structure_form.html', row=row, sessions=None,
            selected_session=row.academic_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )
    if not is_fee_structure_scope_unique(row.academic_session_id, semester_id, department_id, category_id, exclude_id=row.id):
        flash('A fee structure row for this exact session/semester/department/category combination already exists.')
        return render_template(
            'admin/fee_structure_form.html', row=row, sessions=None,
            selected_session=row.academic_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )

    update_fee_structure(fee_structure_id, semester_id, department_id, category_id, amount)
    log_admin_action(current_user, 'fee_structure_updated', target_type='fee_structure', target_id=fee_structure_id,
                      details=f'semester_id={semester_id} department_id={department_id} category_id={category_id} amount={amount}',
                      ip_address=request.remote_addr)
    flash('Fee structure row updated.')
    return redirect(url_for('admin_fee_structures', session_id=row.academic_session_id))


@app.route('/admin/fee-structure/<int:fee_structure_id>/delete', methods=['POST'])
@permission_required('sessions.manage')
def admin_fee_structure_delete(fee_structure_id):
    row = get_fee_structure(fee_structure_id)
    session_id = row.academic_session_id
    delete_fee_structure(fee_structure_id)
    log_admin_action(current_user, 'fee_structure_deleted', target_type='fee_structure', target_id=fee_structure_id,
                      details=f'session_id={session_id}', ip_address=request.remote_addr)
    flash('Fee structure row deleted.')
    return redirect(url_for('admin_fee_structures', session_id=session_id))


@app.route('/admin/registration/open')
@permission_required('registration.manage')
def admin_registration_open():
    periods = list_inactive_periods()
    return render_template('admin/registration_open.html', periods=periods)


@app.route('/admin/registration/oversight')
@permission_required('registration.manage')
def admin_registration_oversight():
    periods = list_periods_for_selector()
    return render_template(
        'admin/registration_oversight.html', periods=periods,
        departments=list_active_departments(), programmes=list_active_programmes(),
    )


@app.route('/admin/registration/oversight/data')
@permission_required('registration.manage')
def admin_registration_oversight_data():
    period_id = request.args.get('period_id', type=int)
    period = RegistrationPeriod.query.get(period_id) if period_id else (
        RegistrationPeriod.query.filter_by(is_active=True).order_by(RegistrationPeriod.id.desc()).first()
    )
    if period is None:
        return jsonify({'success': False, 'message': 'No registration period selected or active.'}), 400

    department_id = request.args.get('department_id', type=int)
    programme_id = request.args.get('programme_id', type=int)
    level = request.args.get('level', '').strip() or None
    status = request.args.get('status', '').strip() or None

    metrics = get_oversight_metrics(period, department_id=department_id, programme_id=programme_id, level=level, status=status)
    return jsonify({
        'success': True, 'period_id': period.id,
        'session_name': period.academic_session.name, 'semester_name': period.semester.name,
        **metrics,
    })


@app.route('/admin/onboarding')
@permission_required('students.manage')
def admin_onboarding_dashboard():
    return render_template(
        'admin/onboarding_dashboard.html', departments=list_active_departments(), programmes=list_active_programmes(),
    )


@app.route('/admin/onboarding/data')
@permission_required('students.manage')
def admin_onboarding_dashboard_data():
    department_id = request.args.get('department_id', type=int)
    programme_id = request.args.get('programme_id', type=int)
    session_value = request.args.get('session', '').strip() or None

    summary = get_onboarding_summary(department_id=department_id, programme_id=programme_id, session=session_value)
    analytics = get_onboarding_analytics()
    return jsonify({'success': True, **summary, 'analytics': analytics})


@app.route('/admin/announcements/new')
@permission_required('announcements.manage')
def admin_stub_announcements_new():
    return render_template('admin/coming_soon.html', feature_name='Create Announcement')


@app.route('/admin/export')
@permission_required('reports.view')
def admin_export_center():
    return render_template('admin/export_center.html')


@app.route('/admin/export/<data_type>/<fmt>')
@permission_required('reports.view')
def admin_export_download(data_type, fmt):
    if data_type not in VALID_DATA_TYPES:
        abort(404)
    if fmt == 'csv':
        response = export_csv(data_type)
    elif fmt == 'xlsx':
        response = export_excel(data_type)
    else:
        abort(404)
    log_admin_action(current_user, 'data_exported', target_type=data_type, details=f'format={fmt}',
                      ip_address=request.remote_addr)
    return response


@app.route('/admin/students/bulk-export', methods=['POST'])
@permission_required('reports.view')
def admin_students_bulk_export():
    data = request.get_json()
    if not data or not data.get('student_ids') or not data.get('format'):
        return jsonify({'success': False, 'message': 'student_ids and format are required.'}), 400

    fmt = data['format']
    student_ids = data['student_ids']
    if fmt == 'csv':
        response = export_csv('students', student_ids=student_ids)
    elif fmt == 'xlsx':
        response = export_excel('students', student_ids=student_ids)
    else:
        return jsonify({'success': False, 'message': 'format must be csv or xlsx.'}), 400

    log_admin_action(current_user, 'student_bulk_exported', target_type='user', target_id=None,
                      details=f'format={fmt} count={len(student_ids)} ids={student_ids}', ip_address=request.remote_addr)
    return response


@app.route('/admin/reports')
@permission_required('reports.view')
def admin_stub_reports():
    return render_template('admin/coming_soon.html', feature_name='Generate Reports')


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