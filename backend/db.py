from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from backend.config import DATABASE_URL

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    # Import models so SQLAlchemy registers all tables before create_all.
    from backend import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
