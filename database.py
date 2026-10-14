from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
from runtime_env import is_production

load_dotenv()

DATABASE_URL = os.getenv("PROD_DATABASE_URL") or os.getenv("DATABASE_URL", "sqlite:///./newsletter.db")
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
if is_production() and DATABASE_URL.startswith('postgresql'):
    connect_args['sslmode'] = 'require'

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


