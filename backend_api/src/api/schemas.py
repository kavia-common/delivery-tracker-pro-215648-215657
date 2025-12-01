from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


# Enums must mirror ORM enums for validation at API boundary
class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


class DeliveryStatus(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELED = "canceled"
    FAILED = "failed"


class NotificationType(str, Enum):
    STATUS_UPDATE = "status_update"
    LOCATION_UPDATE = "location_update"
    SYSTEM = "system"


class NotificationChannel(str, Enum):
    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"
    WEBHOOK = "webhook"


# USER SCHEMAS
class UserBase(BaseModel):
    email: EmailStr = Field(..., description="Unique email address for the user")
    full_name: Optional[str] = Field(None, max_length=255, description="User's full name")
    role: UserRole = Field(default=UserRole.USER, description="User role")
    is_active: bool = Field(default=True, description="Whether the user is active")


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128, description="Plain password")

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if v.strip() != v:
            raise ValueError("Password cannot start or end with whitespace")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=255)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8, max_length=128)


class UserOut(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# DELIVERY SCHEMAS
class DeliveryBase(BaseModel):
    tracking_code: str = Field(..., min_length=3, max_length=64, description="Tracking code")
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, description="Optional delivery description")
    status: DeliveryStatus = Field(default=DeliveryStatus.CREATED)
    courier_name: Optional[str] = Field(None, max_length=128)
    expected_delivery_at: Optional[datetime] = None


class DeliveryCreate(DeliveryBase):
    user_id: int = Field(..., ge=1, description="Owner user id")


class DeliveryUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    status: Optional[DeliveryStatus] = None
    courier_name: Optional[str] = Field(None, max_length=128)
    expected_delivery_at: Optional[datetime] = None


class DeliveryOut(DeliveryBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# LOCATION SCHEMAS
class DeliveryLocationBase(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    altitude_m: Optional[float] = Field(None, description="Altitude in meters")
    accuracy_m: Optional[float] = Field(None, ge=0)
    timestamp: Optional[datetime] = Field(None, description="Optional client timestamp")


class DeliveryLocationCreate(DeliveryLocationBase):
    delivery_id: int = Field(..., ge=1)


class DeliveryLocationOut(DeliveryLocationBase):
    id: int
    delivery_id: int

    class Config:
        from_attributes = True


# STATUS EVENT SCHEMAS
class DeliveryStatusEventBase(BaseModel):
    status: DeliveryStatus
    note: Optional[str] = None
    timestamp: Optional[datetime] = None
    actor_user_id: Optional[int] = Field(None, ge=1)


class DeliveryStatusEventCreate(DeliveryStatusEventBase):
    delivery_id: int = Field(..., ge=1)


class DeliveryStatusEventOut(DeliveryStatusEventBase):
    id: int
    delivery_id: int

    class Config:
        from_attributes = True


# NOTIFICATION EVENT SCHEMAS
class NotificationEventBase(BaseModel):
    type: NotificationType
    channel: NotificationChannel
    title: Optional[str] = Field(None, max_length=255)
    message: str = Field(..., min_length=1)
    sent_success: bool = True
    error: Optional[str] = None


class NotificationEventCreate(NotificationEventBase):
    user_id: int = Field(..., ge=1)
    delivery_id: Optional[int] = Field(None, ge=1)


class NotificationEventOut(NotificationEventBase):
    id: int
    user_id: int
    delivery_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Aggregated views for list/detail endpoints
# PUBLIC_INTERFACE
class DeliveryDetail(BaseModel):
    """Composite delivery payload including latest location and recent status."""

    delivery: DeliveryOut
    latest_location: Optional[DeliveryLocationOut] = None
    recent_status_events: List[DeliveryStatusEventOut] = []

    class Config:
        from_attributes = True
