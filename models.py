from time_utils import utc_now
from sqlalchemy import Column, Integer, String, Boolean, DateTime, UniqueConstraint, Text, Float
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)
    character_name = Column(String, nullable=False)
    character_series = Column(String, nullable=False)
    message_type = Column(String, nullable=False)
    frequency = Column(String, nullable=False)
    daily_time = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    confirmed = Column(Boolean, default=False)
    confirmation_token = Column(String, unique=True, nullable=True)
    unsubscribe_token = Column(String, unique=True, nullable=True)

    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint('email', 'character_name', 'character_series', name='unique_subscription'),
    )


class EmailJob(Base):
    __tablename__ = "email_jobs"
    id = Column(String, primary_key=True)
    dedupe_key = Column(String, unique=True, nullable=False)
    user_id = Column(Integer, nullable=True, index=True)
    payload = Column(Text, nullable=False)
    mode = Column(String, nullable=False, default="preview")
    status = Column(String, nullable=False, default="queued", index=True)
    subject = Column(Text)
    body = Column(Text)
    error = Column(Text)
    model = Column(String)
    attempts = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    available_at = Column(DateTime, default=utc_now, nullable=False)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    delivery_receipt = Column(Text)


class CharacterProfile(Base):
    __tablename__ = "character_profiles"
    id = Column(String, primary_key=True)
    status = Column(String, nullable=False)  # researching, ready, failed
    markdown = Column(Text)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class ModelUsage(Base):
    __tablename__ = "model_usage"
    id = Column(Integer, primary_key=True)
    job_id = Column(String, nullable=False, index=True)
    phase = Column(String, nullable=False)
    model = Column(String, nullable=False)
    input_tokens = Column(Integer, default=0, nullable=False)
    output_tokens = Column(Integer, default=0, nullable=False)
    searches = Column(Integer, default=0, nullable=False)
    cost_usd = Column(Float, nullable=False)
    state = Column(String, default="reserved", nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class SubscriptionSchedule(Base):
    __tablename__ = "subscription_schedules"
    user_id = Column(Integer, primary_key=True)
    next_at = Column(DateTime, nullable=False, index=True)


class SubmissionRate(Base):
    __tablename__ = "submission_rates"
    key = Column(String, primary_key=True)
    count = Column(Integer, default=1, nullable=False)


class EmailDesign(Base):
    __tablename__ = 'email_designs'
    job_id = Column(String, primary_key=True)
    theme = Column(Text, nullable=False)


class AnnouncementCampaign(Base):
    __tablename__ = 'announcement_campaigns'
    id = Column(String, primary_key=True)
    state = Column(String, default='prepared', nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    released_at = Column(DateTime)


class WorkerHeartbeat(Base):
    __tablename__ = 'worker_heartbeat'
    id = Column(Integer, primary_key=True)
    updated_at = Column(DateTime, nullable=False)
