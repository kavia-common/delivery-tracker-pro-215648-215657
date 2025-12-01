from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.api.db import get_db
from src.api.models import (
    Delivery,
    DeliveryLocation,
    DeliveryStatus,
    DeliveryStatusEvent,
)
from src.api.schemas import (
    DeliveryCreate,
    DeliveryDetail,
    DeliveryLocationOut,
    DeliveryOut,
    DeliveryStatusEventOut,
    DeliveryUpdate,
)

router = APIRouter(prefix="/deliveries", tags=["Deliveries"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _assert_owner_or_admin(
    *, resource_user_id: int, current_user: Dict[str, Any]
) -> None:
    """Raises 403 if current user is neither the owner nor an admin."""
    if current_user.get("is_admin"):
        return
    if int(current_user["id"]) != int(resource_user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to access this resource",
        )


def _load_delivery_or_404(db: Session, delivery_id: int) -> Delivery:
    delivery = db.get(Delivery, delivery_id)
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    return delivery


def _delivery_to_out(d: Delivery) -> DeliveryOut:
    return DeliveryOut.model_validate(d)


def _location_to_out(loc: DeliveryLocation) -> DeliveryLocationOut:
    return DeliveryLocationOut.model_validate(loc)


def _status_to_out(ev: DeliveryStatusEvent) -> DeliveryStatusEventOut:
    return DeliveryStatusEventOut.model_validate(ev)


class ListQueryParams(BaseModel):
    """Validated list filters."""

    status: Optional[DeliveryStatus] = Field(None, description="Filter by status")
    user_id: Optional[int] = Field(None, ge=1, description="Filter by owner (admin only)")
    q: Optional[str] = Field(None, description="Search in tracking_code or title")
    limit: int = Field(50, ge=1, le=200, description="Page size")
    offset: int = Field(0, ge=0, description="Page offset")


def _parse_list_params(
    status: Optional[DeliveryStatus],
    user_id: Optional[int],
    q: Optional[str],
    limit: int,
    offset: int,
) -> ListQueryParams:
    return ListQueryParams(status=status, user_id=user_id, q=q, limit=limit, offset=offset)


@router.get(
    "",
    response_model=List[DeliveryOut],
    summary="List deliveries",
    description="List deliveries owned by the current user. Admins can list all and filter.",
)
# PUBLIC_INTERFACE
def list_deliveries(
    status: Optional[DeliveryStatus] = Query(None, description="Filter by status"),
    user_id: Optional[int] = Query(None, ge=1, description="Owner user id (admin only)"),
    q: Optional[str] = Query(None, description="Search in tracking_code or title"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> List[DeliveryOut]:
    """List deliveries.

    - Regular users see only their deliveries.
    - Admins can filter by user_id and status and search.

    Efficient querying:
    - Uses indexed columns (status, user_id, tracking_code).
    """
    params = _parse_list_params(status, user_id, q, limit, offset)
    conditions = []

    if not current_user.get("is_admin"):
        conditions.append(Delivery.user_id == int(current_user["id"]))
    else:
        if params.user_id:
            conditions.append(Delivery.user_id == params.user_id)

    if params.status:
        conditions.append(Delivery.status == params.status)

    if params.q:
        like = f"%{params.q.strip()}%"
        conditions.append(or_(Delivery.tracking_code.ilike(like), Delivery.title.ilike(like)))

    stmt = select(Delivery).where(and_(*conditions)) if conditions else select(Delivery)
    stmt = stmt.order_by(Delivery.created_at.desc()).limit(params.limit).offset(params.offset)

    deliveries = db.scalars(stmt).all()
    return [_delivery_to_out(d) for d in deliveries]


@router.post(
    "",
    response_model=DeliveryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a delivery",
    description="Create a new delivery. Regular users can only assign to themselves.",
)
# PUBLIC_INTERFACE
def create_delivery(
    payload: DeliveryCreate,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> DeliveryOut:
    """Create delivery with ownership and uniqueness checks."""
    # Regular users cannot create deliveries for others
    if not current_user.get("is_admin") and payload.user_id != int(current_user["id"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create for another user")

    # Ensure tracking_code unique (unique constraint exists; this is a fast pre-check)
    existing = db.query(Delivery).filter(Delivery.tracking_code == payload.tracking_code).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tracking code already exists")

    d = Delivery(
        tracking_code=payload.tracking_code,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        user_id=payload.user_id,
        courier_name=payload.courier_name,
        expected_delivery_at=payload.expected_delivery_at,
    )
    db.add(d)
    db.flush()  # to get id for status event

    # Add initial status event
    ev = DeliveryStatusEvent(
        delivery_id=d.id,
        status=d.status,
        note="Initial status",
        timestamp=_utcnow(),
        actor_user_id=int(current_user["id"]),
    )
    db.add(ev)
    db.commit()
    db.refresh(d)

    # Hook: emit realtime event in future (status: created)
    return _delivery_to_out(d)


@router.get(
    "/{delivery_id}",
    response_model=DeliveryDetail,
    summary="Get delivery detail",
    description="Get a delivery with latest location and recent status events.",
)
# PUBLIC_INTERFACE
def get_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> DeliveryDetail:
    """Retrieve a single delivery with related info."""
    d = _load_delivery_or_404(db, delivery_id)
    _assert_owner_or_admin(resource_user_id=d.user_id, current_user=current_user)

    latest_location = (
        db.query(DeliveryLocation)
        .filter(DeliveryLocation.delivery_id == d.id)
        .order_by(DeliveryLocation.timestamp.desc())
        .first()
    )
    recent_status = (
        db.query(DeliveryStatusEvent)
        .filter(DeliveryStatusEvent.delivery_id == d.id)
        .order_by(DeliveryStatusEvent.timestamp.desc())
        .limit(10)
        .all()
    )

    return DeliveryDetail(
        delivery=_delivery_to_out(d),
        latest_location=_location_to_out(latest_location) if latest_location else None,
        recent_status_events=[_status_to_out(s) for s in recent_status],
    )


@router.patch(
    "/{delivery_id}",
    response_model=DeliveryOut,
    summary="Update a delivery",
    description="Partial update delivery fields. Only owner or admin.",
)
# PUBLIC_INTERFACE
def update_delivery(
    delivery_id: int,
    payload: DeliveryUpdate,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> DeliveryOut:
    """Update mutable delivery fields; record status change if provided."""
    d = _load_delivery_or_404(db, delivery_id)
    _assert_owner_or_admin(resource_user_id=d.user_id, current_user=current_user)

    original_status = d.status

    if payload.title is not None:
        d.title = payload.title
    if payload.description is not None:
        d.description = payload.description
    if payload.courier_name is not None:
        d.courier_name = payload.courier_name
    if payload.expected_delivery_at is not None:
        d.expected_delivery_at = payload.expected_delivery_at
    if payload.status is not None and payload.status != d.status:
        d.status = payload.status
        ev = DeliveryStatusEvent(
            delivery_id=d.id,
            status=d.status,
            note="Status updated via PATCH",
            timestamp=_utcnow(),
            actor_user_id=int(current_user["id"]),
        )
        db.add(ev)

    db.commit()
    db.refresh(d)

    # Hook: emit realtime event: status change
    if payload.status is not None and payload.status != original_status:
        pass

    return _delivery_to_out(d)


@router.delete(
    "/{delivery_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a delivery",
    description="Delete a delivery. Only owner or admin.",
)
# PUBLIC_INTERFACE
def delete_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Response:
    """Delete a delivery and its related records."""
    d = _load_delivery_or_404(db, delivery_id)
    _assert_owner_or_admin(resource_user_id=d.user_id, current_user=current_user)

    db.delete(d)
    db.commit()

    # Hook: emit realtime event: deleted
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class StatusUpdateRequest(BaseModel):
    status: DeliveryStatus = Field(..., description="New status")
    note: Optional[str] = Field(None, description="Optional note")
    timestamp: Optional[datetime] = Field(None, description="Client-provided timestamp")


@router.post(
    "/{delivery_id}/status",
    response_model=DeliveryStatusEventOut,
    status_code=status.HTTP_201_CREATED,
    summary="Append a status event",
    description="Add a new status event and update the delivery's current status.",
)
# PUBLIC_INTERFACE
def append_status(
    delivery_id: int,
    payload: StatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> DeliveryStatusEventOut:
    """Append a status event; updates the delivery's status to match."""
    d = _load_delivery_or_404(db, delivery_id)
    _assert_owner_or_admin(resource_user_id=d.user_id, current_user=current_user)

    event_ts = payload.timestamp or _utcnow()
    ev = DeliveryStatusEvent(
        delivery_id=d.id,
        status=payload.status,
        note=payload.note,
        timestamp=event_ts,
        actor_user_id=int(current_user["id"]),
    )
    d.status = payload.status

    db.add(ev)
    db.commit()
    db.refresh(ev)

    # Hook: emit realtime event: status_update
    return _status_to_out(ev)


class LocationIngestRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    altitude_m: Optional[float] = Field(None)
    accuracy_m: Optional[float] = Field(None, ge=0)
    timestamp: Optional[datetime] = Field(None)
    source: Optional[str] = Field(None, description="GPS, device, courier, etc.")


@router.post(
    "/{delivery_id}/location",
    response_model=DeliveryLocationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a location point",
    description="Add a location data point for a delivery. Only owner or admin.",
)
# PUBLIC_INTERFACE
def ingest_location(
    delivery_id: int,
    payload: LocationIngestRequest,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> DeliveryLocationOut:
    """Record a location point for the delivery."""
    d = _load_delivery_or_404(db, delivery_id)
    _assert_owner_or_admin(resource_user_id=d.user_id, current_user=current_user)

    ts = payload.timestamp or _utcnow()
    loc = DeliveryLocation(
        delivery_id=d.id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        altitude_m=payload.altitude_m,
        accuracy_m=payload.accuracy_m,
        timestamp=ts,
        source=payload.source,
    )
    db.add(loc)
    db.commit()
    db.refresh(loc)

    # Hook: emit realtime event: location_update
    return _location_to_out(loc)


@router.get(
    "/export",
    summary="Export deliveries as CSV",
    description="Export deliveries visible to the current user as CSV. Admins can filter.",
    response_class=Response,
)
# PUBLIC_INTERFACE
def export_csv(
    status: Optional[DeliveryStatus] = Query(None),
    user_id: Optional[int] = Query(None, ge=1),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Response:
    """Export deliveries as CSV with basic filters.

    Columns:
    id, tracking_code, title, status, user_id, courier_name, expected_delivery_at, created_at, updated_at
    """
    params = _parse_list_params(status, user_id, q, limit=10_000, offset=0)
    conditions = []

    if not current_user.get("is_admin"):
        conditions.append(Delivery.user_id == int(current_user["id"]))
    else:
        if params.user_id:
            conditions.append(Delivery.user_id == params.user_id)

    if params.status:
        conditions.append(Delivery.status == params.status)
    if params.q:
        like = f"%{params.q.strip()}%"
        conditions.append(or_(Delivery.tracking_code.ilike(like), Delivery.title.ilike(like)))

    stmt = select(Delivery).where(and_(*conditions)) if conditions else select(Delivery)
    stmt = stmt.order_by(Delivery.created_at.desc()).limit(params.limit)
    deliveries = db.scalars(stmt).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "tracking_code",
            "title",
            "status",
            "user_id",
            "courier_name",
            "expected_delivery_at",
            "created_at",
            "updated_at",
        ]
    )
    for d in deliveries:
        writer.writerow(
            [
                d.id,
                d.tracking_code,
                d.title or "",
                d.status.value,
                d.user_id,
                d.courier_name or "",
                (d.expected_delivery_at.isoformat() if d.expected_delivery_at else ""),
                d.created_at.isoformat() if d.created_at else "",
                d.updated_at.isoformat() if d.updated_at else "",
            ]
        )

    csv_bytes = buf.getvalue().encode("utf-8")
    headers = {
        "Content-Disposition": 'attachment; filename="deliveries.csv"',
        "Content-Type": "text/csv; charset=utf-8",
    }
    return Response(content=csv_bytes, media_type="text/csv", headers=headers)
