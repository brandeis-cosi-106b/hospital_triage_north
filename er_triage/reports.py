"""Census and operational reporting for the ER Triage Registry.

All functions in this module are read-only with respect to the registry;
they produce formatted strings or plain-data summaries without mutating state.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Dict, List

from .patient import Patient, acuity_category, acuity_label

if TYPE_CHECKING:
    from .registry import PatientRegistry
    from .ward import EmergencyDepartment, Ward


# ---------------------------------------------------------------------------
# Low-level formatting helpers
# ---------------------------------------------------------------------------

_DIVIDER = "-" * 72
_BOLD_DIVIDER = "=" * 72


def _header(title: str) -> str:
    pad = (_BOLD_DIVIDER.__len__() - len(title) - 2) // 2
    return f"{'=' * pad} {title} {'=' * pad}"


def _patient_row(p: Patient) -> str:
    waited = f"{p.wait_minutes:.0f}m"
    attending = p.attending or "—"
    return (
        f"  {p.patient_id:<10} {p.name:<22} "
        f"A{p.acuity:<3} {p.severity_label:<18} "
        f"{p.chief_complaint:<28} wait={waited:<6} {attending}"
    )


def format_patient_table(patients: List[Patient], title: str = "Patients") -> str:
    """Return a fixed-width table of patients sorted by acuity descending.

    Patients with the same acuity stay in the order they were passed in.
    """
    if not patients:
        return f"{title}: (none)"
    rows = [_header(title)]
    rows.append(
        f"  {'ID':<10} {'Name':<22} {'Ac':<4} {'Severity':<18} "
        f"{'Chief Complaint':<28} {'Wait':<6} Attending"
    )
    rows.append(_DIVIDER)
    for p in sorted(patients, key=lambda x: -x.acuity):
        rows.append(_patient_row(p))
    rows.append(_BOLD_DIVIDER)
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Acuity distribution
# ---------------------------------------------------------------------------


def acuity_distribution(registry: "PatientRegistry") -> Dict[int, int]:
    """Return a dict mapping each acuity level (1–10) to the patient count.

    Read from the registry's per-level tally, so no traversal is needed.
    """
    return registry.acuity_counts()


def department_acuity_distribution(dept: "EmergencyDepartment") -> Dict[int, int]:
    """Return the acuity distribution across both wards of *dept*."""
    counts = acuity_distribution(dept.general.registry)
    for level, n in acuity_distribution(dept.icu.registry).items():
        counts[level] += n
    return counts


def format_acuity_histogram(registry: "PatientRegistry") -> str:
    """Render a simple ASCII histogram of the acuity distribution."""
    return _render_histogram(acuity_distribution(registry))


def _render_histogram(dist: Dict[int, int]) -> str:
    max_count = max(dist.values()) if any(dist.values()) else 1
    bar_width = 30
    lines = [_header("Acuity Distribution")]
    for level in range(10, 0, -1):
        count = dist[level]
        filled = int(bar_width * count / max_count) if max_count else 0
        bar = "█" * filled + "░" * (bar_width - filled)
        label = acuity_label(level)
        lines.append(
            f"  {level:>2} {label:<18} [{bar}] {count:>3}"
        )
    lines.append(_BOLD_DIVIDER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Category summary
# ---------------------------------------------------------------------------


def category_summary(registry: "PatientRegistry") -> Dict[str, int]:
    """Aggregate patient counts by triage colour category."""
    return _categories(acuity_distribution(registry))


def _categories(dist: Dict[int, int]) -> Dict[str, int]:
    totals: Dict[str, int] = {"Green": 0, "Yellow": 0, "Orange": 0, "Red": 0}
    for level, count in dist.items():
        totals[acuity_category(level)] += count
    return totals


def format_category_summary(registry: "PatientRegistry") -> str:
    return _render_categories(category_summary(registry))


def _render_categories(summary: Dict[str, int]) -> str:
    lines = [_header("Triage Category Summary")]
    colours = {"Green": "🟢", "Yellow": "🟡", "Orange": "🟠", "Red": "🔴"}
    for cat, count in summary.items():
        icon = colours.get(cat, " ")
        lines.append(f"  {icon}  {cat:<8} {count:>4} patient(s)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ward-level reports
# ---------------------------------------------------------------------------


def ward_report(ward: "Ward") -> str:
    """Full report for a single ward including patient table and stats."""
    patients = ward.triage_order()
    lines = [
        format_patient_table(patients, title=ward.config.name),
        f"  Occupancy : {ward.occupancy():>3} / {ward.config.capacity} "
        f"({ward.occupancy_pct():.1f}%)",
    ]
    if patients:
        avg = sum(p.acuity for p in patients) / len(patients)
        lines.append(f"  Avg acuity: {avg:.2f}")
        lines.append(f"  Most acute: {ward.most_acute()}")
    return "\n".join(lines)


def department_report(dept: "EmergencyDepartment") -> str:
    """Comprehensive report spanning both wards of an EmergencyDepartment.

    The acuity histogram and the category summary cover the whole department.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dist = department_acuity_distribution(dept)
    sections = [
        _bold_divider_line(f"{dept.name.upper()} — DEPARTMENT REPORT"),
        f"  Generated : {ts}",
        f"  Total census : {dept.total_occupancy()} patient(s)",
        "",
        ward_report(dept.general),
        "",
        ward_report(dept.icu),
        "",
        _render_histogram(dist),
        "",
        _render_categories(_categories(dist)),
        _BOLD_DIVIDER,
    ]
    return "\n".join(sections)


def _bold_divider_line(title: str) -> str:
    return _header(title)


# ---------------------------------------------------------------------------
# Load metrics
# ---------------------------------------------------------------------------


def critical_load(dept: "EmergencyDepartment", threshold: int = 8) -> dict:
    """Return a dict of load metrics relative to *threshold*.

    Keys
    ----
    critical_count   : critical patients in the department (general ward + ICU)
    general_critical : critical patients still in the general ward
    icu_count        : total ICU occupancy
    icu_pct          : ICU occupancy as a percentage of ICU capacity
    """
    critical = dept.critical_count(threshold)
    icu_count = dept.icu.occupancy()
    return {
        "critical_count":   critical,
        "general_critical": dept.general.count_in_range(threshold, 10),
        "icu_count":        icu_count,
        "icu_pct":          100.0 * icu_count / dept.icu.config.capacity,
    }


def format_load_metrics(dept: "EmergencyDepartment", threshold: int = 8) -> str:
    metrics = critical_load(dept, threshold)
    lines = [
        _header(f"Load Metrics (threshold = {threshold})"),
        f"  Critical patients (acuity >= {threshold}) : {metrics['critical_count']:>3}",
        f"    Still in general ward                  : {metrics['general_critical']:>3}",
        f"  ICU census                               : {metrics['icu_count']:>3}",
        f"  ICU occupancy                            : {metrics['icu_pct']:.1f}%",
    ]
    return "\n".join(lines)
