"""Patient data model for the ER Triage Registry."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Acuity helpers
# ---------------------------------------------------------------------------

MIN_ACUITY = 1
MAX_ACUITY = 10

_ACUITY_LABELS: dict[int, str] = {
    1:  "Non-urgent",
    2:  "Low",
    3:  "Moderate",
    4:  "Urgent",
    5:  "High",
    6:  "Very High",
    7:  "Severe",
    8:  "Critical",
    9:  "Life-threatening",
    10: "Immediate",
}

# Colour-coded triage categories (Green / Yellow / Orange / Red)
_CATEGORY_BOUNDS: list[tuple[range, str]] = [
    (range(1, 4),  "Green"),
    (range(4, 7),  "Yellow"),
    (range(7, 9),  "Orange"),
    (range(9, 11), "Red"),
]


def acuity_label(acuity: int) -> str:
    """Return the severity label for a given acuity score (1–10)."""
    return _ACUITY_LABELS.get(acuity, "Unknown")


def acuity_category(acuity: int) -> str:
    """Return the triage colour category for a given acuity score."""
    for r, cat in _CATEGORY_BOUNDS:
        if acuity in r:
            return cat
    return "Unknown"


def validate_acuity(acuity: object) -> None:
    """Raise ValueError unless *acuity* is an integer score from 1 to 10."""
    is_int = isinstance(acuity, int) and not isinstance(acuity, bool)
    if not is_int or not (MIN_ACUITY <= acuity <= MAX_ACUITY):
        raise ValueError(
            f"Acuity must be an integer between 1 and 10, got {acuity!r}."
        )


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------

@dataclass
class Patient:
    """Represents a single patient in the ER triage system.

    Attributes
    ----------
    name:              Full name of the patient.
    acuity:            Clinical severity score, 1 (non-urgent) to 10 (immediate).
    chief_complaint:   Primary presenting symptom or reason for visit.
    patient_id:        Unique 8-character identifier assigned at admission.
    arrival_time:      Timestamp when the patient arrived.
    notes:             Free-text clinical notes accumulated during the visit.
    attending:         Name of the assigned attending physician, if any.

    The acuity score is checked on construction and on every later assignment.
    While a patient is admitted, change the score through
    PatientRegistry.reassess() (or the Ward / EmergencyDepartment method of the
    same name) so that the registry can re-file the record.  Assigning
    patient.acuity directly on an admitted patient leaves the registry's index
    out of date.
    """

    name: str
    acuity: int
    chief_complaint: str
    patient_id: str = field(
        default_factory=lambda: str(uuid.uuid4()).replace("-", "")[:8].upper()
    )
    arrival_time: datetime = field(default_factory=datetime.now)
    notes: str = ""
    attending: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Patient name cannot be empty.")

    def __setattr__(self, name: str, value: object) -> None:
        if name == "acuity":
            validate_acuity(value)
        super().__setattr__(name, value)

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def severity_label(self) -> str:
        """Human-readable severity string (e.g. 'Critical')."""
        return acuity_label(self.acuity)

    @property
    def triage_category(self) -> str:
        """Colour-coded triage category (Green / Yellow / Orange / Red)."""
        return acuity_category(self.acuity)

    @property
    def is_critical(self) -> bool:
        """True if the patient has acuity ≥ 8."""
        return self.acuity >= 8

    @property
    def wait_minutes(self) -> float:
        """Elapsed time in minutes since arrival."""
        return (datetime.now() - self.arrival_time).total_seconds() / 60.0

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def add_note(self, note: str) -> None:
        """Prepend a timestamped note to the patient's record."""
        ts = datetime.now().strftime("%H:%M")
        self.notes = f"[{ts}] {note}\n" + self.notes

    def assign_attending(self, physician_name: str) -> None:
        """Assign or reassign the attending physician."""
        self.attending = physician_name

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def summary_line(self) -> str:
        """Single-line summary suitable for console output."""
        attended = f" | Attending: {self.attending}" if self.attending else ""
        return (
            f"[{self.patient_id}] {self.name:<20} "
            f"Acuity {self.acuity:>2} ({self.severity_label:<16}) "
            f"CC: {self.chief_complaint}{attended}"
        )

    def __str__(self) -> str:
        return self.summary_line()

    def __repr__(self) -> str:
        return (
            f"Patient(name={self.name!r}, acuity={self.acuity}, "
            f"id={self.patient_id!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Patient):
            return NotImplemented
        return self.patient_id == other.patient_id

    def __hash__(self) -> int:
        return hash(self.patient_id)
