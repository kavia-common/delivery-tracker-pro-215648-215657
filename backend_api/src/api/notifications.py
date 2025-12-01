from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.api.db import get_db
from src.api.models import NotificationEvent
from src.api.schemas import NotificationEventOut

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ListNotificationsQuery(BaseModel):
    unread_only: bool = Field(default=False, description="If true, only return unread notifications")
    since_hours: Optional[int] = Field(
        default=None, ge=1, le=720,
        description="If provided, only notifications created within the last N hours"
    )
    q: Optional[str] = Field(
        default=None, description="Search in title or message (ilike)"
    )
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    delivery_id: Optional[int] = Field(default=None, ge=1, description="Filter by delivery id")


# PUBLIC_INTERFACE
@router.get(
    "",
    response_model=List[NotificationEventOut],
    summary="List recent notifications",
    description="List recent notifications for the current user with optional filters and pagination.",
)
def list_notifications(
    unread_only: bool = Query(False, description="Only unread notifications"),
    since_hours: Optional[int] = Query(
        None, ge=1, le=720, description="Only notifications within the last N hours"
    ),
    q: Optional[str] = Query(None, description="Search in title or message (ilike)"),
    delivery_id: Optional[int] = Query(None, ge=1, description="Filter by delivery id"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> List[NotificationEventOut]:
    """Return notifications belonging to the current user.

    Filters:
    - unread_only: if True, only sent_success == True and error is NULL and updated_at==created_at (unread) will be returned.
    - since_hours: restrict results to events created after now-<hours>.
    - q: case-insensitive search in title or message.
    - delivery_id: filter by related delivery.

    Results are ordered by created_at desc for recency.
    """
    params = ListNotificationsQuery(
        unread_only=unread_only,
        since_hours=since_hours,
        q=q,
        limit=limit,
        offset=offset,
        delivery_id=delivery_id,
    )

    # Base: user ownership
    conditions = [NotificationEvent.user_id == int(current_user["id"])]

    # Unread heuristic: If we had a read_at field we'd use it; since we don't, treat unread as "not acknowledged"
    # Here we interpret "unread" as events the client has not marked as read yet; we will add an endpoint that updates updated_at to 'acknowledged' state.
    # To keep behavior deterministic without extra columns, we assume:
    # - unread: updated_at == created_at (hasn't been modified by mark-as-read)
    if params.unread_only:
        conditions.append(NotificationEvent.updated_at == NotificationEvent.created_at)

    if params.since_hours:
        window_start = _utcnow() - timedelta(hours=params.since_hours)
        conditions.append(NotificationEvent.created_at >= window_start)

    if params.delivery_id:
        conditions.append(NotificationEvent.delivery_id == params.delivery_id)

    if params.q:
        like = f"%{params.q.strip()}%"
        conditions.append(or_(NotificationEvent.title.ilike(like), NotificationEvent.message.ilike(like)))

    stmt = select(NotificationEvent).where(and_(*conditions)).order_by(desc(NotificationEvent.created_at)).limit(params.limit).offset(params.offset)
    items = db.scalars(stmt).all()
    return [NotificationEventOut.model_validate(n) for n in items]


class MarkReadRequest(BaseModel):
    ids: List[int] = Field(..., description="Notification IDs to mark as read", min_length=1)
    read_all_unread: bool = Field(
        False,
        description="If true, ignore ids and mark all unread notifications as read for the current user",
    )


class MarkReadResult(BaseModel):
    updated_count: int = Field(..., description="How many notification records were marked as read")


# PUBLIC_INTERFACE
@router.post(
    "/read",
    response_model=MarkReadResult,
    summary="Mark notifications as read",
    description="Mark specified notifications as read, or all unread ones for the current user.",
    status_code=status.HTTP_200_OK,
)
def mark_notifications_read(
    payload: MarkReadRequest,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> MarkReadResult:
    """Mark notifications as read for the requesting user.

    Since we don't maintain a read_at column, we record the read action by updating updated_at to current time.
    Only notifications belonging to the current user are updated.
    """
    now = _utcnow()
    q_base = db.query(NotificationEvent).filter(NotificationEvent.user_id == int(current_user["id"]))

    if payload.read_all_unread:
        # Only those not updated since creation (unread heuristic)
        q_target = q_base.filter(NotificationEvent.updated_at == NotificationEvent.created_at)
        updated = 0
        for n in q_target.all():
            n.updated_at = now
            updated += 1
        db.commit()
        return MarkReadResult(updated_count=updated)

    if not payload.ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No notification ids provided")

    q_target = q_base.filter(NotificationEvent.id.in_(payload.ids))
    updated = 0
    for n in q_target.all():
        n.updated_at = now
        updated += 1
    db.commit()
    return MarkReadResult(updated_count=updated)
