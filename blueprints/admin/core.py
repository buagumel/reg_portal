from flask import Blueprint, request, jsonify, render_template
from flask_login import current_user

from models import RegistrationPeriod
from services.admin_dashboard import get_dashboard_summary, get_activity_feed
from services.admin_permission import permission_required, get_visible_quick_actions, enforce_admin_required
from services.admin_session import list_inactive_periods
from services.admin_registration import list_periods_for_selector, get_oversight_metrics
from services.admin_department import list_active_departments
from services.admin_student import list_active_programmes
from services.admin_onboarding import get_onboarding_summary, get_onboarding_analytics

admin_core_bp = Blueprint('core', __name__)
admin_core_bp.before_request(enforce_admin_required)


@admin_core_bp.route('/admin/dashboard')
@permission_required('dashboard.view')
def admin_dashboard():
    summary = get_dashboard_summary()
    activity_feed = get_activity_feed(limit=20)
    quick_actions = get_visible_quick_actions(current_user)
    return render_template(
        'admin/admin_dashboard.html',
        summary=summary, activity_feed=activity_feed, quick_actions=quick_actions,
    )


@admin_core_bp.route('/admin/registration/open')
@permission_required('registration.manage')
def admin_registration_open():
    periods = list_inactive_periods()
    return render_template('admin/registration_open.html', periods=periods)


@admin_core_bp.route('/admin/registration/oversight')
@permission_required('registration.manage')
def admin_registration_oversight():
    periods = list_periods_for_selector()
    return render_template(
        'admin/registration_oversight.html', periods=periods,
        departments=list_active_departments(), programmes=list_active_programmes(),
    )


@admin_core_bp.route('/admin/registration/oversight/data')
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


@admin_core_bp.route('/admin/onboarding')
@permission_required('students.manage')
def admin_onboarding_dashboard():
    return render_template(
        'admin/onboarding_dashboard.html', departments=list_active_departments(), programmes=list_active_programmes(),
    )


@admin_core_bp.route('/admin/onboarding/data')
@permission_required('students.manage')
def admin_onboarding_dashboard_data():
    department_id = request.args.get('department_id', type=int)
    programme_id = request.args.get('programme_id', type=int)
    session_value = request.args.get('session', '').strip() or None

    summary = get_onboarding_summary(department_id=department_id, programme_id=programme_id, session=session_value)
    analytics = get_onboarding_analytics()
    return jsonify({'success': True, **summary, 'analytics': analytics})


@admin_core_bp.route('/admin/announcements/new')
@permission_required('announcements.manage')
def admin_stub_announcements_new():
    return render_template('admin/coming_soon.html', feature_name='Create Announcement')


from blueprints.admin import admin_bp  # noqa: E402 — deferred import to avoid a circular import with blueprints/admin/__init__.py

admin_bp.register_blueprint(admin_core_bp)
