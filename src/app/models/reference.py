"""Lookup tables loaded from IDs_mapping.csv or built from the data."""
from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base


class RefAdmissionType(Base):
    """admission_type_id -> description."""

    __tablename__ = "ref_admission_type"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    description: Mapped[str] = mapped_column(String(100), nullable=False)


class RefAdmissionSource(Base):
    """admission_source_id -> description."""

    __tablename__ = "ref_admission_source"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    description: Mapped[str] = mapped_column(String(150), nullable=False)


class RefDischargeDisposition(Base):
    """discharge_disposition_id -> description; flags expired/hospice discharges."""

    __tablename__ = "ref_discharge_disposition"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    is_expired_or_hospice: Mapped[bool] = mapped_column(default=False, server_default="0", nullable=False)


class RefMedicalSpecialty(Base):
    """Distinct medical_specialty values found in the data."""

    __tablename__ = "ref_medical_specialty"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    specialty_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)


class RefPayer(Base):
    """Distinct payer_code values found in the data."""

    __tablename__ = "ref_payer"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    payer_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payer_code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
