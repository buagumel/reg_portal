import csv
import io
import json

from models import db


def parse_csv(file_storage, required_headers):
    """Reads an uploaded CSV FileStorage. Returns (rows, error) where rows is
    a list of dicts (one per data row, keyed by header) and error is None on
    success, or (None, error_message) if the file can't be read or is missing
    a required header."""
    if not file_storage or not file_storage.filename:
        return None, 'No file was uploaded.'
    if not file_storage.filename.lower().endswith('.csv'):
        return None, 'File must be a .csv file.'

    try:
        raw = file_storage.stream.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        return None, 'File is not valid UTF-8 text.'

    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames is None:
        return None, 'File is empty.'

    missing = [h for h in required_headers if h not in reader.fieldnames]
    if missing:
        return None, f'Missing required column(s): {", ".join(missing)}.'

    rows = list(reader)
    if not rows:
        return None, 'File has a header row but no data rows.'
    return rows, None


def create_import_job(job_model, admin_user, filename):
    job = job_model(admin_user_id=admin_user.id, filename=filename, status='processing')
    db.session.add(job)
    db.session.commit()
    return job


def record_import_error(error_model, job, row_number, raw_row, reason):
    error = error_model(
        import_job_id=job.id,
        row_number=row_number,
        raw_row=json.dumps(raw_row),
        reason=reason,
    )
    db.session.add(error)


def finalize_import_job(job, created, updated, skipped, duplicates, errors):
    from models import now_lagos
    job.created_count = created
    job.updated_count = updated
    job.skipped_count = skipped
    job.duplicate_count = duplicates
    job.error_count = errors
    job.status = 'completed'
    job.completed_at = now_lagos()
    db.session.commit()
