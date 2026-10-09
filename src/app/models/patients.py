"""Patients: the only place race and gender are stored."""
from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import MYSQL_TABLE_ARGS, Base, SoftDeleteMixin, TimestampMixin


class Patient(Base, SoftDeleteMixin, TimestampMixin):
    """One row per patient_nbr (source key, never auto-generated)."""

    __tablename__ = "patients"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    patient_nbr: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    race: Mapped[str | None] = mapped_column(String(30), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)

    encounters = relationship("Encounter", back_populates="patient")
