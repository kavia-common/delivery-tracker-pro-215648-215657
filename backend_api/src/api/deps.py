from typing import Any, Dict

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.db import get_db


# PUBLIC_INTERFACE
def get_current_user(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Placeholder dependency to get the current authenticated user.

    Args:
        db (Session): SQLAlchemy session (unused in placeholder).

    Returns:
        Dict[str, Any]: A mock user object for scaffolding purposes.

    Note:
        Replace with real JWT verification and user lookup.
    """
    # Placeholder: return a fake user; in real implementation, decode JWT and fetch user
    return {"id": "user_1", "email": "user@example.com", "is_admin": False}


# PUBLIC_INTERFACE
def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Dependency to ensure the current user has admin privileges.

    Args:
        user (Dict[str, Any]): Current user object.

    Returns:
        Dict[str, Any]: The same user object if admin.

    Raises:
        HTTPException: 403 if user is not an admin.

    Note:
        Replace with real role/permission checks.
    """
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )
    return user
