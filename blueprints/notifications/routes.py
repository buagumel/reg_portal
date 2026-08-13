from flask import request, jsonify
from flask_login import current_user, login_required

from blueprints.notifications import notifications_bp
from services.notification import (
    get_notifications, get_summary_counts,
    mark_read, mark_unread, mark_all_read, archive_notification, delete_notification,
)


@notifications_bp.route('/notifications/data')
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


@notifications_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def notification_mark_read(notification_id):
    notification = mark_read(current_user, notification_id)
    if notification is None:
        return jsonify({'success': False, 'message': 'Notification not found.'}), 404
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@notifications_bp.route('/notifications/<int:notification_id>/unread', methods=['POST'])
@login_required
def notification_mark_unread(notification_id):
    notification = mark_unread(current_user, notification_id)
    if notification is None:
        return jsonify({'success': False, 'message': 'Notification not found.'}), 404
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@notifications_bp.route('/notifications/<int:notification_id>/archive', methods=['POST'])
@login_required
def notification_archive(notification_id):
    notification = archive_notification(current_user, notification_id)
    if notification is None:
        return jsonify({'success': False, 'message': 'Notification not found.'}), 404
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@notifications_bp.route('/notifications/<int:notification_id>/delete', methods=['POST'])
@login_required
def notification_delete(notification_id):
    notification = delete_notification(current_user, notification_id)
    if notification is None:
        return jsonify({'success': False, 'message': 'Notification not found.'}), 404
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@notifications_bp.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def notification_mark_all_read():
    mark_all_read(current_user)
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})
