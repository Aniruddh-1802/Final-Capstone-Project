"""Encounters: one row per hospital encounter."""
from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Enum, ForeignKey, Index, Integer, SmallInteger, String
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import MYSQL_TABLE_ARGS, Base, SoftDeleteMixin, TimestampMixin

GLUCOSE_VALUES = ("None", "Norm", ">200", ">300")
A1C_VALUES = ("None", "Norm", ">7", ">8")


class Encounter(Base, SoftDeleteMixin, TimestampMixin):
    """encounter_id is the source key. admission_date / discharge_date are SIMULATED."""

    __tablename__ = "encounters"
    # Date-range lists and trends always filter is_deleted = 0 and then a range on admission_date (see docs/performance_notes.md).
    __table_args__ = (Index("ix_encounters_is_deleted_admission_date", "is_deleted", "admission_date"), MYSQL_TABLE_ARGS)

    encounter_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    patient_nbr: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.patient_nbr", ondelete="RESTRICT"), nullable=False
    )
    admission_date: Mapped[date] = mapped_column(Date, nullable=False)  # simulated
    discharge_date: Mapped[date] = mapped_column(Date, nullable=False)  # simulated
    age_group: Mapped[str] = mapped_column(String(10), nullable=False)
    age_order: Mapped[int] = mapped_column(TINYINT(unsigned=True), nullable=False)
    admission_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ref_admission_type.id", ondelete="RESTRICT"), nullable=False
    )
    discharge_disposition_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ref_discharge_disposition.id", ondelete="RESTRICT"), nullable=False
    )
    admission_source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ref_admission_source.id", ondelete="RESTRICT"), nullable=False
    )
    specialty_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ref_medical_specialty.specialty_id", ondelete="RESTRICT"), nullable=True
    )
    payer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ref_payer.payer_id", ondelete="RESTRICT"), nullable=True
    )
    time_in_hospital: Mapped[int] = mapped_column(TINYINT(unsigned=True), nullable=False)
    num_lab_procedures: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    num_procedures: Mapped[int] = mapped_column(TINYINT(unsigned=True), nullable=False)
    num_medications: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    number_outpatient: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    number_emergency: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    number_inpatient: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    number_diagnoses: Mapped[int] = mapped_column(TINYINT(unsigned=True), nullable=False)
    max_glu_serum: Mapped[str] = mapped_column(Enum(*GLUCOSE_VALUES, name="max_glu_serum"), nullable=False)
    a1c_result: Mapped[str] = mapped_column(Enum(*A1C_VALUES, name="a1c_result"), nullable=False)
    med_changed: Mapped[bool] = mapped_column(nullable=False)
    diabetes_med: Mapped[bool] = mapped_column(nullable=False)
    source_batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    patient = relationship("Patient", back_populates="encounters")
    outcome = relationship("EncounterOutcome", back_populates="encounter", uselist=False,
                           cascade="all, delete-orphan", passive_deletes=True)
    diagnoses = relationship("EncounterDiagnosis", back_populates="encounter",
                             cascade="all, delete-orphan", passive_deletes=True)
    medications = relationship("EncounterMedication", back_populates="encounter",
                               cascade="all, delete-orphan", passive_deletes=True)
