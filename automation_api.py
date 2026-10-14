from time_utils import utc_now
import hashlib
import hmac
import json
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import schemas
from automation_config import Settings
from automation_queue import character_id, enqueue
from database import get_db
from email_design import stored_theme
from automation_delivery import email_parts
from runtime_env import is_production


def require_admin(x_admin_token: str = Header(default='')):
    if is_production() or os.getenv('ADMIN_ENDPOINTS_ENABLED', 'true').lower() != 'true':
        raise HTTPException(404, 'Not found')
    configured = os.getenv('ADMIN_API_TOKEN', '')
    if not configured or not hmac.compare_digest(x_admin_token.encode(), configured.encode()):
        raise HTTPException(401, 'Valid X-Admin-Token required')


def limit_submissions(request: Request, email: str, db: Session):
    # DB-backed counter works across API processes. Configure proxy trust in Uvicorn;
    # never trust arbitrary X-Forwarded-For headers in application code.
    hour = utc_now().strftime('%Y-%m-%dT%H')
    for identity, maximum in [(request.client.host if request.client else 'unknown', 10), (email.casefold(), 3)]:
        key = hour + ':' + hashlib.sha256(identity.encode()).hexdigest()
        changed = db.query(models.SubmissionRate).filter(models.SubmissionRate.key == key, models.SubmissionRate.count < maximum).update({'count': models.SubmissionRate.count + 1})
        if not changed:
            if db.get(models.SubmissionRate, key):
                db.rollback()
                raise HTTPException(429, 'Too many subscriptions; try again next hour')
            try:
                with db.begin_nested():
                    db.add(models.SubmissionRate(key=key))
                    db.flush()
            except IntegrityError:
                db.rollback()
                raise HTTPException(429, 'Please retry later')
        db.commit()
    db.query(models.SubmissionRate).filter(models.SubmissionRate.key < utc_now().strftime('%Y-%m-%d')).delete()
    db.commit()


router = APIRouter(prefix='/api/admin/automation', dependencies=[Depends(require_admin)])


def job_view(db, job):
    usage = db.query(models.ModelUsage).filter_by(job_id=job.id).all()
    html_preview = email_parts(job, theme=stored_theme(db, job))[1] if job.body else None
    return {'id': job.id, 'status': job.status, 'mode': job.mode, 'request': json.loads(job.payload),
            'subject': job.subject, 'body': job.body, 'error': job.error, 'model': job.model,
            'html_preview': html_preview,
            'attempts': job.attempts, 'created_at': job.created_at, 'started_at': job.started_at,
            'finished_at': job.finished_at,
            'processing_seconds': (job.finished_at - job.started_at).total_seconds() if job.finished_at and job.started_at else None,
            'estimated_cost_usd': sum(item.cost_usd for item in usage),
            'usage': [{'phase': item.phase, 'model': item.model, 'input_tokens': item.input_tokens,
                       'output_tokens': item.output_tokens, 'searches': item.searches,
                       'cost_usd': item.cost_usd, 'state': item.state} for item in usage]}


@router.get('/status')
def status(db: Session = Depends(get_db)):
    settings = Settings()
    month = utc_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = db.query(func.coalesce(func.sum(models.ModelUsage.cost_usd), 0)).filter(models.ModelUsage.created_at >= month).scalar()
    return {'mode': settings.mode, 'model': settings.model, 'monthly_cost_usd': total,
            'monthly_budget_usd': settings.monthly_budget, 'request_budget_usd': settings.request_budget,
            'timezone': settings.timezone, 'scheduler_enabled': settings.scheduler}


@router.get('/jobs')
def jobs(db: Session = Depends(get_db)):
    return [job_view(db, job) for job in db.query(models.EmailJob).order_by(models.EmailJob.created_at.desc()).limit(50)]


@router.post('/jobs', status_code=202)
def create_job(data: schemas.CharacterEmailRequest, idempotency_key: str = Header(default=''), db: Session = Depends(get_db)):
    settings = Settings()
    if not data.preview and settings.mode != 'send':
        raise HTTPException(409, 'Set AUTOMATION_MODE=send on API and worker to enable delivery')
    if len(idempotency_key) > 150:
        raise HTTPException(422, 'Idempotency key too long')
    try:
        job = enqueue(db, data.model_dump(exclude={'preview'}), 'preview' if data.preview else 'send', 'admin:' + idempotency_key if idempotency_key else None)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return job_view(db, job)


@router.post('/jobs/{job_id}/send', status_code=202)
def send_preview(job_id: str, db: Session = Depends(get_db)):
    if Settings().mode != 'send':
        raise HTTPException(409, 'Enable AUTOMATION_MODE=send on API and worker first')
    job = db.get(models.EmailJob, job_id)
    if job is None:
        raise HTTPException(404, 'Job not found')
    # Atomic transition makes repeated clicks harmless.
    changed = db.query(models.EmailJob).filter_by(id=job_id, status='preview').update({
        'status': 'queued', 'mode': 'send', 'available_at': utc_now(), 'attempts': 0, 'error': None, 'finished_at': None})
    db.commit()
    if not changed:
        raise HTTPException(409, 'Only a completed preview can be sent')
    db.refresh(job)
    return job_view(db, job)


@router.post('/jobs/{job_id}/retry', status_code=202)
def retry_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(models.EmailJob, job_id)
    if job is None:
        raise HTTPException(404, 'Job not found')
    changed = db.query(models.EmailJob).filter(models.EmailJob.id == job_id, models.EmailJob.status.in_(['failed', 'budget_blocked'])).update({
        'status': 'queued', 'available_at': utc_now(), 'attempts': 0, 'error': None, 'finished_at': None})
    db.commit()
    if not changed:
        raise HTTPException(409, 'Only failed or budget-blocked generation can be retried; uncertain delivery cannot')
    db.refresh(job)
    return job_view(db, job)


@router.put('/profiles')
def import_profile(data: schemas.ProfileImport, db: Session = Depends(get_db)):
    key = character_id(data.character_name, data.character_series)
    profile = db.get(models.CharacterProfile, key)
    if profile and profile.status == 'researching':
        raise HTTPException(409, 'Research is in progress; stop the worker before repairing an interrupted lookup')
    if profile is None:
        profile = models.CharacterProfile(id=key, status='ready')
        db.add(profile)
    profile.markdown, profile.status, profile.updated_at = data.markdown, 'ready', utc_now()
    db.commit()
    # Worker mirrors authoritative DB profiles into Markdown before use.
    return {'character_id': key, 'status': 'ready'}
