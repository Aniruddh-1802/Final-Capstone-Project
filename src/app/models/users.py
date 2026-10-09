"""Application users for authentication and RBAC."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base

ROLES = ("administrator", "clinical_ops", "analyst")


class AppUser(Base):
    """A login account. Only the bcrypt hash is stored."""

    __tablename__ = "app_users"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(Enum(*ROLES, name="user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
