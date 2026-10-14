"""Deployment checks without printing credentials or connection strings."""
import os
from sqlalchemy import inspect, text
from database import Base, engine
from runtime_env import is_production


def validate_environment(role):
    if not is_production():
        return
    if engine.dialect.name != 'postgresql':
        raise RuntimeError('Production requires the existing Supabase PostgreSQL database, not SQLite')
    if engine.url.port == 6543:
        raise RuntimeError('Use a Supabase direct or session pooler connection (port 5432); transaction pooling cannot hold the worker lock')
    if not os.getenv('FRONTEND_URL', '').startswith('https://'):
        raise RuntimeError('Production FRONTEND_URL must be your public HTTPS frontend origin')
    origins = os.getenv('CORS_ORIGINS', os.getenv('FRONTEND_URL', '')).split(',')
    if any(not origin.strip().startswith('https://') for origin in origins):
        raise RuntimeError('Production CORS_ORIGINS must contain explicit HTTPS origins')
    if role in {'web', 'worker'}:
        from automation_delivery import validate_delivery_settings
        validate_delivery_settings()
    if role == 'web' and any(not os.getenv(key, '').strip() for key in ('MAILJET_API_KEY', 'MAILJET_API_SECRET', 'MAILJET_SENDER_EMAIL')):
        raise RuntimeError('The API needs Mailjet credentials for subscription confirmations')
    if role == 'worker' and not os.getenv('ANTHROPIC_API_KEY', '').strip():
        raise RuntimeError('Set ANTHROPIC_API_KEY on the worker')


def initialize_database():
    if is_production():
        from schema_bootstrap import initialize_tables
        initialize_tables()
    else:
        Base.metadata.create_all(engine)
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
