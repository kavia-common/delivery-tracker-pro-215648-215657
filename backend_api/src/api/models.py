from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.api.db import Base


class UserRole(str, Enum):
    """Logical roles for users within the system."""

    USER = "user"
    ADMIN = "admin"


class DeliveryStatus(str, Enum):
    """Lifecycle states for a delivery."""

    CREATED = "created"
    ASSIGNED = "assigned"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELED = "canceled"
    FAILED = "failed"


class NotificationType(str, Enum):
    """Types of notification events that can be sent to users/admins."""

    STATUS_UPDATE = "status_update"
    LOCATION_UPDATE = "location_update"
    SYSTEM = "system"


class NotificationChannel(str, Enum):
    """Channels over which notifications may be delivered."""

    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"
    WEBHOOK = "webhook"


class TimestampMixin:
    """Common created_at/updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(Base, TimestampMixin):
    """User model representing application users."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_email", "email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.USER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    deliveries: Mapped[List["Delivery"]] = relationship(
        "Delivery",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notifications: Mapped[List["NotificationEvent"]] = relationship(
        "NotificationEvent",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Delivery(Base, TimestampMixin):
    """Delivery model representing an item being delivered for a user."""

    __tablename__ = "deliveries"
    __table_args__ = (
        Index("ix_deliveries_tracking_code", "tracking_code"),
        UniqueConstraint("tracking_code", name="uq_deliveries_tracking_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tracking_code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[DeliveryStatus] = mapped_column(
        SAEnum(DeliveryStatus),
        default=DeliveryStatus.CREATED,
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional courier/driver info
    courier_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    expected_delivery_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="deliveries")
    locations: Mapped[List["DeliveryLocation"]] = relationship(
        "DeliveryLocation",
        back_populates="delivery",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DeliveryLocation.timestamp.desc()",
    )
    status_events: Mapped[List["DeliveryStatusEvent"]] = relationship(
        "DeliveryStatusEvent",
        back_populates="delivery",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DeliveryStatusEvent.timestamp.desc()",
    )
    notifications: Mapped[List["NotificationEvent"]] = relationship(
        "NotificationEvent",
        back_populates="delivery",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DeliveryLocation(Base):
    """Time-stamped geolocation data points for a delivery."""

    __tablename__ = "delivery_locations"
    __table_args__ = (
        Index("ix_delivery_locations_delivery_id_ts", "delivery_id", "timestamp"),
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_lat_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_lng_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    delivery_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    # altitude in meters, optional
    altitude_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    delivery: Mapped["Delivery"] = relationship("Delivery", back_populates="locations")


class DeliveryStatusEvent(Base):
    """Historical status changes for a delivery."""

    __tablename__ = "delivery_status_events"
    __table_args__ = (Index("ix_delivery_status_events_delivery_id_ts", "delivery_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    delivery_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[DeliveryStatus] = mapped_column(SAEnum(DeliveryStatus), nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    delivery: Mapped["Delivery"] = relationship("Delivery", back_populates="status_events")
    actor_user: Mapped[Optional["User"]] = relationship("User")


class NotificationEvent(Base, TimestampMixin):
    """Notification send history for users or admins related to deliveries."""

    __tablename__ = "notification_events"
    __table_args__ = (
        Index("ix_notification_events_user_id_created_at", "user_id", "created_at"),
        Index("ix_notification_events_delivery_id_created_at", "delivery_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    delivery_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=True, index=True
    )
    type: Mapped[NotificationType] = mapped_column(SAEnum(NotificationType), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel), nullable=False
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    sent_success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="notifications")
    delivery: Mapped[Optional["Delivery"]] = relationship("Delivery", back_populates="notifications")
