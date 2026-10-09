"""Child tables of encounters: outcomes, diagnoses, medications."""
from __future__ import annotations

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import MYSQL_TABLE_ARGS, Base

READMITTED_VALUES = ("NO", ">30", "<30")
DOSAGE_VALUES = ("Steady", "Up", "Down")


class EncounterOutcome(Base):
    """One outcome per encounter, including the derived flags (computed once, in the ETL)."""

    __tablename__ = "encounter_outcomes"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    encounter_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("encounters.encounter_id", ondelete="CASCADE"),
        primary_key=True, autoincrement=False,
    )
    readmitted: Mapped[str] = mapped_column(Enum(*READMITTED_VALUES, name="readmitted"), nullable=False)
    readmitted_30d: Mapped[bool] = mapped_column(nullable=False)
    any_readmission: Mapped[bool] = mapped_column(nullable=False)
    is_readmission_eligible: Mapped[bool] = mapped_column(nullable=False)

    encounter = relationship("Encounter", back_populates="outcome")


class EncounterDiagnosis(Base):
    """Up to three ICD-9 codes per encounter; position 1 is the primary diagnosis. Always strings."""

    __tablename__ = "encounter_diagnoses"
    # ICD-9 prefix search (LIKE 'V57%') uses this index; a leading wildcard never would.
    __table_args__ = (Index("ix_encounter_diagnoses_icd9_code", "icd9_code"), MYSQL_TABLE_ARGS)

    encounter_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("encounters.encounter_id", ondelete="CASCADE"),
        primary_key=True, autoincrement=False,
    )
    position: Mapped[int] = mapped_column(TINYINT(unsigned=True), primary_key=True, autoincrement=False)
    icd9_code: Mapped[str] = mapped_column(String(10), nullable=False)

    encounter = relationship("Encounter", back_populates="diagnoses")


class Medication(Base):
    """The drug names (snake_case)."""

    __tablename__ = "medications"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    medication_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    drug_name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)


class EncounterMedication(Base):
    """Drugs prescribed in an encounter. 'No' rows are never stored."""

    __tablename__ = "encounter_medications"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    encounter_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("encounters.encounter_id", ondelete="CASCADE"),
        primary_key=True, autoincrement=False,
    )
    medication_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("medications.medication_id", ondelete="RESTRICT"),
        primary_key=True, autoincrement=False,
    )
    dosage_status: Mapped[str] = mapped_column(Enum(*DOSAGE_VALUES, name="dosage_status"), nullable=False)

    encounter = relationship("Encounter", back_populates="medications")
    medication = relationship("Medication")
