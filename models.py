from sqlalchemy import Column, Integer, String, Boolean, DateTime, UniqueConstraint
from database import Base
import datetime

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

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('email', 'character_name', 'character_series', name='unique_subscription'),
    )