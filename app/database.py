import os
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


DATABASE_URL = os.environ.get("SUPABASE_DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "SUPABASE_DATABASE_URL environment variable is not set"
    )


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


Base = declarative_base()
