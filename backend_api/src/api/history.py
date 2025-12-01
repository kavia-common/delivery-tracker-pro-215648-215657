from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from src.api.deps import get_current_user
from src.api.db import get_db
from src.api.models import (
    Delivery,
    DeliveryStatus,
    DeliveryStatusEvent,
)
from src.api.schemas import DeliveryOut, DeliveryStatusEventOut


router = APIRouter(prefix="/history", tags=["History"])


class PageMeta(BaseModel):
    total: int = Field(..., description="Total items for this query")
    limit: int = Field(..., description="Limit (page size)")
    offset: int = Field(..., description="Offset (page start index)")


class PaginatedDeliveryHistory(BaseModel):
    items: List[DeliveryOut]
    meta: PageMeta


class PaginatedStatusEvents(BaseModel):
    items: List[DeliveryStatusEventOut]
    meta: PageMeta


def _ensure_actor_or_admin_access_filters(
    current_user: Dict[str, Any],
    user_id: Optional[int],
) -> List[Any]:
    """Build user access filter clauses."""
    conditions: List[Any] = []
    if current_user.get("is_admin"):
        if user_id:
            conditions.append(Delivery.user_id == user_id)
    else:
        # regular users can only see their own records regardless of user_id param
        conditions.append(Delivery.user_id == int(current_user["id"]))
    return conditions


# PUBLIC_INTERFACE
@router.get(
    "",
    response_model=PaginatedDeliveryHistory,
    summary="Query historical deliveries",
    description="Query deliveries over time with optional filters (date range, status, courier) and pagination.",
)
def list_history(
    start_date: Optional[datetime] = Query(
        None, description="Created from (inclusive). ISO8601 datetime."
    ),
    end_date: Optional[datetime] = Query(
        None, description="Created until (inclusive). ISO8601 datetime."
    ),
    status_filter: Optional[DeliveryStatus] = Query(None, description="Filter by delivery status"),
    courier: Optional[str] = Query(None, description="Filter by courier/driver name (ilike)"),
    user_id: Optional[int] = Query(None, ge=1, description="Owner user id (admin only)"),
    q: Optional[str] = Query(None, description="Search tracking_code or title (ilike)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> PaginatedDeliveryHistory:
    """Query deliveries visible to the requester with various filters and pagination.

    Filters:
    - start_date/end_date on created_at (inclusive bounds)
    - status equals
    - courier ilike
    - q: search tracking_code or title (ilike)
    - user_id: only for admins; regular users restricted to own id

    Performance:
    - Uses indices on deliveries.status, deliveries.user_id, deliveries.tracking_code, created_at.
    - Orders by created_at desc.
    """
    conditions: List[Any] = _ensure_actor_or_admin_access_filters(current_user, user_id)
    if start_date:
        conditions.append(Delivery.created_at >= start_date)
    if end_date:
        conditions.append(Delivery.created_at <= end_date)
    if status_filter:
        conditions.append(Delivery.status == status_filter)
    if courier:
        conditions.append(Delivery.courier_name.ilike(f"%{courier.strip()}%"))
    if q:
        like = f"%{q.strip()}%"
        conditions.append(or_(Delivery.tracking_code.ilike(like), Delivery.title.ilike(like)))

    base_stmt = select(Delivery).where(and_(*conditions)) if conditions else select(Delivery)

    # Count total first (subquery for accuracy with filters)
    count_stmt = base_stmt.with_only_columns(Delivery.id).order_by(None)
    total = db.execute(count_stmt).all()
    total_count = len(total)

    stmt = (
        base_stmt.order_by(Delivery.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    deliveries = db.scalars(stmt).all()
    return PaginatedDeliveryHistory(
        items=[DeliveryOut.model_validate(d) for d in deliveries],
        meta=PageMeta(total=total_count, limit=limit, offset=offset),
    )


# PUBLIC_INTERFACE
@router.get(
    "/status-events",
    response_model=PaginatedStatusEvents,
    summary="Query status history",
    description="Query status events joined with deliveries and filtered by date range, status, courier and pagination.",
)
def list_status_events(
    start_date: Optional[datetime] = Query(
        None, description="Event timestamp from (inclusive). ISO8601 datetime."
    ),
    end_date: Optional[datetime] = Query(
        None, description="Event timestamp until (inclusive). ISO8601 datetime."
    ),
    status_filter: Optional[DeliveryStatus] = Query(None, description="Filter by status"),
    courier: Optional[str] = Query(None, description="Filter by courier/driver name (ilike)"),
    user_id: Optional[int] = Query(None, ge=1, description="Owner user id (admin only)"),
    q: Optional[str] = Query(None, description="Search delivery tracking_code/title (ilike)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> PaginatedStatusEvents:
    """Query delivery status events with joins to deliveries for filtering/context.

    Access control:
    - Regular users: only events for their deliveries.
    - Admins: may filter by user_id or see all.

    Filters:
    - start_date/end_date on event timestamp
    - status equals
    - courier ilike (on delivery.courier_name)
    - q matches delivery.tracking_code or delivery.title
    """
    # Build join with deliveries to ensure access check and filter availability
    q_events = (
        select(DeliveryStatusEvent)
        .join(Delivery, Delivery.id == DeliveryStatusEvent.delivery_id)
        .options(joinedload(DeliveryStatusEvent.delivery))
    )

    conditions: List[Any] = []
    if current_user.get("is_admin"):
        if user_id:
            conditions.append(Delivery.user_id == user_id)
    else:
        conditions.append(Delivery.user_id == int(current_user["id"]))

    if start_date:
        conditions.append(DeliveryStatusEvent.timestamp >= start_date)
    if end_date:
        conditions.append(DeliveryStatusEvent.timestamp <= end_date)
    if status_filter:
        conditions.append(DeliveryStatusEvent.status == status_filter)
    if courier:
        conditions.append(Delivery.courier_name.ilike(f"%#{courier.strip()}%".replace("#", "")))
    if q:
        like = f"%{q.strip()}%"
        conditions.append(or_(Delivery.tracking_code.ilike(like), Delivery.title.ilike(like)))

    if conditions:
        q_events = q_events.where(and_(*conditions))

    # Count using ids only
    count_stmt = q_events.with_only_columns(DeliveryStatusEvent.id).order_by(None)
    total = db.execute(count_stmt).all()
    total_count = len(total)

    q_events = (
        q_events.order_by(DeliveryStatusEvent.timestamp.desc())
        .limit(limit)
        .offset(offset)
    )
    events = db.scalars(q_events).all()

    return PaginatedStatusEvents(
        items=[DeliveryStatusEventOut.model_validate(ev) for ev in events],
        meta=PageMeta(total=total_count, limit=limit, offset=offset),
    )
