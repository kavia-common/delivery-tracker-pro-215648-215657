from typing import Any, Dict

from fastapi import Depends
from sqlalchemy.orm import Session

from src.api.db import get_db
from src.api.auth import get_current_user as _auth_get_current_user, require_admin as _auth_require_admin


# PUBLIC_INTERFACE
def get_current_user(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Dependency to get the current authenticated user using JWT.

    This delegates to the auth module's implementation to avoid duplication.
    """
    return _auth_get_current_user(db=db)  # type: ignore[arg-type]


# PUBLIC_INTERFACE
def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Dependency to ensure the current user has admin privileges."""
    return _auth_require_admin(user)  # type: ignore[arg-type]
