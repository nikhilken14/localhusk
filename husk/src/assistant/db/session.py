from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from assistant.db.engine import engine

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
