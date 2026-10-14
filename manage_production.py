"""Operator CLI. No public admin endpoints are required in production."""
import argparse
import hashlib
import json
import re
import secrets
import uuid
from pathlib import Path

from sqlalchemy import func, text

import models
from automation_config import Settings
from automation_queue import next_delivery, user_payload, character_id
from database import Base, SessionLocal, engine
from email_design import render_email, stored_theme
from production import validate_environment
from schema_bootstrap import initialize_tables
from time_utils import utc_now

CAMPAIGN = 'automatic-delivery-v1'


def campaign_jobs(db, campaign_id):
    return db.query(models.EmailJob).filter(models.EmailJob.dedupe_key.like(f'announcement:{campaign_id}:%'))


def prepare_announcement(db, settings, campaign_id=CAMPAIGN):
    if not re.fullmatch(r'[a-z0-9-]{1,64}', campaign_id):
        raise ValueError('Campaign identifiers must contain lowercase letters, digits and hyphens')
    # A transaction-level lock serializes operator invocations without stopping the worker.
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(847320147)'))
    campaign = db.get(models.AnnouncementCampaign, campaign_id)
    if campaign:
        return campaign_jobs(db, campaign_id).count()
    campaign = models.AnnouncementCampaign(id=campaign_id)
    db.add(campaign)
    users = db.query(models.User).filter(models.User.confirmed == True,
        models.User.frequency.in_(['daily', 'weekly', 'monthly'])).order_by(models.User.created_at, models.User.id).all()
    seen = set()
    now = utc_now()
    for user in users:
        if not user.unsubscribe_token:
            user.unsubscribe_token = secrets.token_urlsafe(32)
        # Seed schedules for all existing subscriptions to avoid a welcome-message flood.
        if db.get(models.SubscriptionSchedule, user.id) is None:
            db.add(models.SubscriptionSchedule(user_id=user.id, next_at=next_delivery(user, now, settings)))
        db.query(models.EmailJob).filter(models.EmailJob.user_id == user.id,
            models.EmailJob.dedupe_key.like('welcome:%'), models.EmailJob.status.in_(['queued', 'preview'])).update(
                {'status': 'cancelled'}, synchronize_session=False)
        email = user.email.casefold().strip()
        if email in seen:
            continue
        seen.add(email)
        digest = hashlib.sha256(email.encode()).hexdigest()
        payload = dict(user_payload(user), purpose='automation_update')
        db.add(models.EmailJob(id=str(uuid.uuid4()), dedupe_key=f'announcement:{campaign_id}:{digest}',
            user_id=user.id, payload=json.dumps(payload), mode='preview', status='queued'))
    db.commit()  # Snapshot audience and queue all previews atomically.
    return len(seen)


def release_announcement(db, settings, campaign_id=CAMPAIGN):
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(847320147)'))
    campaign = db.get(models.AnnouncementCampaign, campaign_id)
    if campaign is None:
        raise ValueError('Prepare this campaign first')
    if campaign.state == 'released':
        return 0
    if settings.mode != 'send':
        raise ValueError('Set AUTOMATION_MODE=send on the CLI and worker before release')
    jobs = campaign_jobs(db, campaign_id).all()
    if any(job.status not in {'preview', 'cancelled'} for job in jobs):
        raise ValueError('Every active announcement must have a completed preview before release; inspect status and fix failed jobs first')
    count = 0
    for job in jobs:
        if job.status == 'cancelled':
            continue
        if not job.body or not job.subject:
            raise ValueError('A preview has no generated content')
        user = db.get(models.User, job.user_id)
        if user is None or not user.confirmed or user.created_at > job.created_at:
            job.status = 'cancelled'
            continue
        job.status, job.mode, job.available_at = 'queued', 'send', utc_now()
        job.attempts, job.error, job.finished_at = 0, None, None
        count += 1
    campaign.state, campaign.released_at = 'released', utc_now()
    db.commit()
    return count


def retry_generation(db, job_id):
    changed = db.query(models.EmailJob).filter(models.EmailJob.id == job_id,
        models.EmailJob.status.in_(['failed', 'budget_blocked'])).update({
            'status': 'queued', 'available_at': utc_now(), 'attempts': 0, 'error': None, 'finished_at': None})
    if not changed:
        raise ValueError('Only failed/budget-blocked generation can be retried; delivery_unknown must be reconciled with the provider')
    db.commit()


def report(db, campaign_id):
    jobs = campaign_jobs(db, campaign_id)
    counts = {status: count for status, count in jobs.with_entities(models.EmailJob.status, func.count()).group_by(models.EmailJob.status)}
    failures = [{'id': job.id, 'status': job.status, 'error': job.error} for job in jobs.filter(models.EmailJob.status.in_(['failed', 'budget_blocked', 'delivery_unknown']))]
    return {'campaign': campaign_id, 'counts': counts, 'failures': failures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init-db', 'prepare-announcement', 'announcement-status', 'export-previews', 'release-announcement', 'retry-generation', 'import-profile'])
    parser.add_argument('--campaign', default=CAMPAIGN)
    parser.add_argument('--directory', default='review')
    parser.add_argument('--job')
    parser.add_argument('--file')
    parser.add_argument('--character')
    parser.add_argument('--series')
    args = parser.parse_args()
    validate_environment('operator')
    if args.action == 'init-db':
        # Additive tables only; existing subscriber rows are not replaced or migrated.
        initialize_tables()
        print('Database tables initialized. Existing subscribers preserved.')
        return
    settings = Settings()
    with SessionLocal() as db:
        if args.action == 'prepare-announcement':
            print(json.dumps({'preview_jobs': prepare_announcement(db, settings, args.campaign)}))
        elif args.action == 'release-announcement':
            print(json.dumps({'released_jobs': release_announcement(db, settings, args.campaign)}))
        elif args.action == 'retry-generation':
            if not args.job:
                parser.error('--job is required')
            retry_generation(db, args.job)
            print('Generation queued; no ambiguous email sends are replayed.')
        elif args.action == 'import-profile':
            if not all((args.file, args.character, args.series)):
                parser.error('--file, --character and --series are required')
            from schemas import ProfileImport
            data = ProfileImport(character_name=args.character, character_series=args.series,
                                 markdown=Path(args.file).read_text(encoding='utf-8'))
            key = character_id(data.character_name, data.character_series)
            profile = db.get(models.CharacterProfile, key)
            if profile and profile.status == 'researching':
                raise ValueError('Research is active; stop/restart the worker to recover an interrupted lookup before importing')
            if profile is None:
                profile = models.CharacterProfile(id=key)
                db.add(profile)
            profile.status, profile.markdown, profile.updated_at = 'ready', data.markdown, utc_now()
            db.commit()
            print('Reviewed profile stored; retry failed generation when ready.')
        elif args.action == 'export-previews':
            target = Path(args.directory)
            target.mkdir(parents=True, exist_ok=True)
            count = 0
            for job in campaign_jobs(db, args.campaign).filter_by(status='preview'):
                (target / (job.id + '.html')).write_text(render_email(job, theme=stored_theme(db, job))[1], encoding='utf-8')
                count += 1
            print(json.dumps({'exported': count, 'directory': str(target.resolve())}))
        else:
            print(json.dumps(report(db, args.campaign), indent=2))


if __name__ == '__main__':
    main()
