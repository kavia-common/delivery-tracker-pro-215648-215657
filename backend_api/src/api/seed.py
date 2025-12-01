from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.auth import _pwd_context  # reuse the existing passlib context
from src.api.db import get_engine
from src.api.models import (
    Delivery,
    DeliveryStatus,
    DeliveryStatusEvent,
    NotificationChannel,
    NotificationEvent,
    NotificationType,
    User,
    UserRole,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _hash_password(plain_password: str) -> str:
    """Hash a plain password using the shared passlib context."""
    return _pwd_context.hash(plain_password)


def _ensure_indexes(engine) -> None:
    """
    Ensure key composite indexes exist using raw SQL (if running against a DB
    that does not auto-create them via SQLAlchemy metadata for any reason).

    This is safe and idempotent when used with PostgreSQL due to IF NOT EXISTS.
    For other DBs, SQLAlchemy's metadata.create_all already covers declared indexes.
    """
    ddl_statements = [
        # These match the __table_args__ declared in models, guarded for idempotency.
        "CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email)",

        "CREATE INDEX IF NOT EXISTS ix_deliveries_tracking_code ON deliveries (tracking_code)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_deliveries_tracking_code ON deliveries (tracking_code)",
        "CREATE INDEX IF NOT EXISTS ix_deliveries_status ON deliveries (status)",
        "CREATE INDEX IF NOT EXISTS ix_deliveries_user_id ON deliveries (user_id)",

        "CREATE INDEX IF NOT EXISTS ix_delivery_locations_delivery_id_ts ON delivery_locations (delivery_id, timestamp)",

        "CREATE INDEX IF NOT EXISTS ix_delivery_status_events_delivery_id_ts ON delivery_status_events (delivery_id, timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_delivery_status_events_status ON delivery_status_events (status)",

        "CREATE INDEX IF NOT EXISTS ix_notification_events_user_id_created_at ON notification_events (user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_notification_events_delivery_id_created_at ON notification_events (delivery_id, created_at)",
    ]
    with engine.begin() as conn:
        for ddl in ddl_statements:
            try:
                conn.execute(text(ddl))
            except Exception:
                # Some engines or existing schemas may not support this exact DDL.
                # Ignore failures silently to keep startup resilient and idempotent.
                pass


def _get_or_create_admin(db: Session) -> User:
    """
    Get admin user if exists; otherwise create it with a placeholder password.
    Email: admin@example.com
    Password: Admin123! (hashed)
    """
    admin_email = "admin@example.com"
    user = db.query(User).filter(User.email == admin_email).first()
    if user:
        # Ensure role is ADMIN if previously created differently
        if user.role != UserRole.ADMIN:
            user.role = UserRole.ADMIN
            db.commit()
            db.refresh(user)
        return user

    admin = User(
        email=admin_email,
        password_hash=_hash_password("Admin123!"),
        full_name="Admin",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _maybe_seed_sample_delivery(db: Session, admin_user: User) -> Optional[Delivery]:
    """
    Create a sample delivery with an initial status event if there are no deliveries.

    The created delivery will belong to the admin user to simplify initial usage.
    """
    existing = db.query(Delivery).first()
    if existing:
        return None

    d = Delivery(
        tracking_code="SAMPLE-TRACK-001",
        title="Sample Delivery",
        description="This is a seeded sample delivery record.",
        status=DeliveryStatus.CREATED,
        user_id=admin_user.id,
        courier_name="Sample Courier",
    )
    db.add(d)
    db.flush()  # ensure d.id

    ev = DeliveryStatusEvent(
        delivery_id=d.id,
        status=DeliveryStatus.CREATED,
        note="Initial seeded status",
        timestamp=_now_utc(),
        actor_user_id=admin_user.id,
    )
    db.add(ev)

    note_msg = f"Delivery {d.tracking_code} created with status '{d.status.value}'."
    notif = NotificationEvent(
        user_id=d.user_id,
        delivery_id=d.id,
        type=NotificationType.STATUS_UPDATE,
        channel=NotificationChannel.PUSH,
        title="Delivery created",
        message=note_msg,
        sent_success=True,
        error=None,
    )
    db.add(notif)

    db.commit()
    db.refresh(d)
    return d


# PUBLIC_INTERFACE
def run_startup_seed(db: Session) -> None:
    """
    Idempotent startup seed routine.

    - Ensures performance indexes exist (no-op if already present).
    - Ensures there is an admin user (admin@example.com) with a hashed placeholder password.
    - Seeds a sample delivery with an initial status event if the deliveries table is empty.

    Args:
        db: SQLAlchemy Session bound to the application engine.
    """
    # Ensure indexes exist (especially in environments where metadata may not have created them)
    engine = get_engine()
    _ensure_indexes(engine)

    # Create or update the admin user
    admin = _get_or_create_admin(db)

    # Seed a sample delivery and initial status if none exist
    _ = _maybe_seed_sample_delivery(db, admin)
