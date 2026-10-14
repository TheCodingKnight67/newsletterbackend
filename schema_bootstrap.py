"""Additive, transactional schema setup for existing Supabase deployments."""
from sqlalchemy import text
from database import Base, engine


def initialize_tables():
    with engine.begin() as connection:
        if engine.dialect.name == 'postgresql':
            # Serialize web/worker deploys so create_all checks cannot race.
            connection.execute(text('SELECT pg_advisory_xact_lock(847320148)'))
        Base.metadata.create_all(connection)
        if engine.dialect.name == 'postgresql':
            quote = engine.dialect.identifier_preparer.quote
            roles = connection.execute(text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")).scalars().all()
            for table in Base.metadata.sorted_tables:
                identifier = quote(table.name)
                connection.execute(text(f'ALTER TABLE {identifier} ENABLE ROW LEVEL SECURITY'))
                for role in ['PUBLIC', *roles]:
                    role_name = quote(role) if role != 'PUBLIC' else 'PUBLIC'
                    connection.execute(text(f'REVOKE ALL ON TABLE {identifier} FROM {role_name}'))
