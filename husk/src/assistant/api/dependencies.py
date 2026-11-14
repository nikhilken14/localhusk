from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from assistant.db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Pagination:
    def __init__(self, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        self.limit = limit
        self.offset = offset


PageParams = Depends(Pagination)
