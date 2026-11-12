# ER Triage Registry

A data-driven emergency room triage management system written in Python.

## Overview

The ER Triage Registry tracks patients across an emergency department, supporting
fast admission, discharge, and ward-level operations based on clinical acuity scores.

Acuity is scored on a 1–10 scale where **10 = immediately life-threatening** and
**1 = non-urgent**. The system supports efficient range counts (e.g., "how many
patients currently have acuity ≥ 8?") and threshold-based escalation (e.g.,
"transfer all critical patients to the ICU").

## Structure

```
er_triage/          Core library
  patient.py        Patient data model
  _store.py         Internal sorted index (private)
  registry.py       PatientRegistry — primary public API
  ward.py           Ward and EmergencyDepartment models
  reports.py        Census and load reporting

simulation/         Standalone ER simulation harness
  data_generator.py Random patient / scenario generation
  simulator.py      Discrete-event simulation loop

tests/              Pytest test suite
```

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

pytest                         # run test suite
python -m simulation.simulator # run a sample simulation
```

## Usage

```python
from er_triage import PatientRegistry, EmergencyDepartment

dept = EmergencyDepartment("County General ER")

dept.admit("Maria Santos",  acuity=9, chief_complaint="chest pain")
dept.admit("Jerome Okafor", acuity=3, chief_complaint="sprained ankle")
dept.admit("Lin Wei",       acuity=7, chief_complaint="severe abdominal pain")

print(dept.general.registry.most_acute())   # next patient to be seen
dept.escalate_critical(threshold=8)         # move acuity >= 8 to ICU
print(dept.census())
```

## How the department behaves

**Triage order.** Patients are seen in order of acuity, highest first. Two
patients with the same acuity are seen first come, first served: whoever was
admitted to the ward earlier goes first. `most_acute()` returns the patient at
the head of that order and `triage_order()` returns the whole queue.

**Escalation and ICU beds.** `escalate_critical(threshold)` moves general-ward
patients at or above the threshold into the ICU. The ICU never goes over its
capacity. When there are more candidates than free beds, the beds go to the
candidates in triage order and the others wait in the general ward, keeping
their place, until a later call finds room. A ward's `min_acuity` and
`max_acuity` settings describe its intended case mix and are advisory only.

**Reassessment.** `reassess(patient_id, new_acuity)` records a new score for a
patient who is already admitted. The patient stays in the same ward and takes
a place in the triage order behind the patients already at the new score.

**Performance.** Admission, "most acute", and splitting a ward at a threshold
are O(log n) expected. Range counts are read from a per-level tally in
constant time. Anything that looks a patient up by ID is a linear scan.

## Acuity Scale

| Score | Label                      | Category |
|-------|----------------------------|----------|
| 1–3   | Non-urgent–Moderate        | Green    |
| 4–6   | Urgent–Very High           | Yellow   |
| 7–8   | Severe–Critical            | Orange   |
| 9–10  | Life-threatening–Immediate | Red      |

The colour category is for display. "Critical" in the API (`is_critical`,
`critical_patients()`, the default escalation threshold) means acuity ≥ 8,
which is the top of Orange plus all of Red.
