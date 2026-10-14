from time_utils import utc_now
import calendar
import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

import models


def character_id(name, series):
    def normalize(value):
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    def slug(value):
        result = re.sub(r"[^\w]+", "-", normalize(value), flags=re.UNICODE).strip("-")[:70] or "character"
        reserved = {'con', 'prn', 'aux', 'nul'} | {f'{prefix}{number}' for prefix in ('com', 'lpt') for number in range(1, 10)}
        return 'character-' + result if result in reserved else result

    # The hash also distinguishes names which collapse to the same filesystem slug.
    suffix = hashlib.sha256(json.dumps([normalize(series), normalize(name)], ensure_ascii=False).encode()).hexdigest()[:12]
    return f"{slug(series)}/{slug(name)}-{suffix}"


def enqueue(db, payload, mode, dedupe_key=None, user_id=None):
    key = dedupe_key or str(uuid.uuid4())
    existing = db.query(models.EmailJob).filter_by(dedupe_key=key).first()
    if existing:
        # Idempotency keys cannot silently point to a different request.
        if json.loads(existing.payload) != payload or existing.mode != mode or existing.user_id != user_id:
            raise ValueError("Idempotency key was already used for another request")
        return existing
    job = models.EmailJob(id=str(uuid.uuid4()), dedupe_key=key, user_id=user_id,
                          payload=json.dumps(payload), mode=mode)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return enqueue(db, payload, mode, key, user_id)
    db.refresh(job)
    return job


def user_payload(user):
    return {"email": user.email, "character_name": user.character_name,
            "character_series": user.character_series, "message_type": user.message_type,
            "notes": user.notes or ""}


def next_delivery(user, after, settings):
    """Return the next UTC slot after `after`; weekly/monthly use signup anniversary."""
    if user.frequency not in {'daily', 'weekly', 'monthly'}:
        raise ValueError('Unsupported subscription schedule')
    zone = ZoneInfo(settings.timezone)
    local = after.replace(tzinfo=timezone.utc).astimezone(zone)
    anchor = user.created_at.replace(tzinfo=timezone.utc).astimezone(zone)
    hours = [settings.morning_hour]
    if user.frequency == "daily":
        hours = {"morning": [settings.morning_hour], "bedtime": [settings.bedtime_hour],
                 "both": [settings.morning_hour, settings.bedtime_hour]}.get(user.daily_time, hours)
    for offset in range(370):
        day = local.date() + timedelta(days=offset)
        if user.frequency == "weekly" and day.weekday() != anchor.weekday():
            continue
        if user.frequency == "monthly" and day.day != min(anchor.day, calendar.monthrange(day.year, day.month)[1]):
            continue
        for hour in hours:
            candidate = datetime.combine(day, datetime.min.time(), tzinfo=zone).replace(hour=hour)
            if candidate > local:
                return candidate.astimezone(timezone.utc).replace(tzinfo=None)
    raise ValueError("Unsupported subscription schedule")


def schedule_due(db, settings, now=None):
    now = now or utc_now()
    query = db.query(models.User).filter(models.User.confirmed == True, models.User.frequency.in_(['daily', 'weekly', 'monthly']))
    users = query.all()
    for user in users:
        lifetime = f"{user.id}:{user.created_at.isoformat()}"
        schedule = db.get(models.SubscriptionSchedule, user.id)
        if schedule is None:
            # Welcome email once per confirmed subscription, including existing subscribers.
            key = f"welcome:{lifetime}"
            if not db.query(models.EmailJob).filter_by(dedupe_key=key).first():
                enqueue(db, user_payload(user), settings.mode, key, user.id)
            db.add(models.SubscriptionSchedule(user_id=user.id, next_at=next_delivery(user, now, settings)))
            db.commit()
        elif schedule.next_at <= now:
            key = f"scheduled:{lifetime}:{schedule.next_at.isoformat()}"
            if not db.query(models.EmailJob).filter_by(dedupe_key=key).first():
                enqueue(db, user_payload(user), settings.mode, key, user.id)
            # Missed slots are coalesced into one message, avoiding a restart flood.
            schedule.next_at = next_delivery(user, now, settings)
            db.commit()
