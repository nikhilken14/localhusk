"""Task API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistant.api.dependencies import get_db
from assistant.core.errors import APIError
from assistant.core.textutil import LIKE_ESCAPE, like_pattern
from assistant.core.timeutil import ensure_utc
from assistant.db.models import Task
from assistant.schemas.productivity import (
    Status,
    TaskIn,
    TaskOut,
    TaskPatch,
    TaskStatusIn,
)
from assistant.services import productivity as prod
from assistant.services.automation import fire_event


router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get(db: Session, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise APIError(404, "Task not found")
    return task


def _payload(task: Task, **extra) -> dict:
    return {
        "id": task.id,
        "task": task.task,
        "status": task.status,
        "due_at": task.due_at,
        "position": task.position,
        **extra,
    }


@router.get("", response_model=list[TaskOut])
def list_tasks(
    status: Status | None = None,
    q: str | None = None,
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """List tasks. Time-based filters (due_before / due_after / overdue) were removed."""
    stmt = select(Task)

    if status is not None:
        stmt = stmt.where(Task.status == status)

    if q and q.strip():
        pattern = like_pattern(q.strip())
        stmt = stmt.where(
            Task.task.ilike(pattern, escape=LIKE_ESCAPE)
        )

    stmt = stmt.order_by(
        Task.status,
        Task.position,
        Task.created_at,
        Task.id,
    ).limit(limit)

    return db.scalars(stmt).all()


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskIn,
    db: Session = Depends(get_db),
):
    task = prod.create_task(
        db,
        task=payload.task,
        status=payload.status,
        due_at=(
            ensure_utc(payload.due_at)
            if payload.due_at is not None
            else None
        ),
        position=payload.position,
    )

    fire_event(db, "task.created", _payload(task))

    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskOut)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
):
    return _get(db, task_id)


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: str,
    payload: TaskPatch,
    db: Session = Depends(get_db),
):
    task = _get(db, task_id)
    data = payload.model_dump(exclude_unset=True)

    new_status = data.pop("status", None)
    position = data.pop("position", None)
    previous_status = task.status

    # Only updates task text and due date.
    prod.update_task(task, changes=data)

    if new_status is not None:
        prod.apply_task_status(
            db,
            task,
            new_status,
            position,
        )
    elif position is not None:
        prod.apply_task_status(
            db,
            task,
            task.status,
            position,
        )

    if new_status is not None and new_status != previous_status:
        fire_event(
            db,
            "task.status_changed",
            _payload(
                task,
                from_status=previous_status,
                to_status=new_status,
            ),
        )

    db.commit()
    db.refresh(task)
    return task


@router.patch(
    "/{task_id}/status",
    response_model=TaskOut,
    summary="Move a task between Kanban columns",
)
def update_task_status(
    task_id: str,
    payload: TaskStatusIn,
    db: Session = Depends(get_db),
):
    task = _get(db, task_id)

    previous_status = prod.apply_task_status(
        db,
        task,
        payload.status,
        payload.position,
    )

    if payload.status != previous_status:
        fire_event(
            db,
            "task.status_changed",
            _payload(
                task,
                from_status=previous_status,
                to_status=payload.status,
            ),
        )

    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=204)
def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
) -> Response:
    task = _get(db, task_id)
    old_status = task.status

    db.delete(task)
    db.flush()

    # Compact the column after deletion.
    remaining = list(
        db.scalars(
            select(Task)
            .where(Task.status == old_status)
            .order_by(Task.position, Task.created_at, Task.id)
        ).all()
    )

    for index, item in enumerate(remaining):
        item.position = index

    db.commit()
    return Response(status_code=204)