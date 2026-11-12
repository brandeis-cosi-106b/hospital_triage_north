"""
Internal patient storage layer.

Provides the backing store used by PatientRegistry to maintain patients and
support fast admission, range counting, and ward partitioning.

This module is private to the er_triage package.  Consumers should interact
only with PatientRegistry and Ward, which provide the stable public interface.
"""

from __future__ import annotations

import random
from typing import Dict, Iterator, List, Optional, Tuple

from .patient import MAX_ACUITY, MIN_ACUITY, Patient

# ---------------------------------------------------------------------------
# Internal tree node
# ---------------------------------------------------------------------------


class _Node:
    """A single node in the acuity-sorted index tree.

    Each node stores one patient, a randomly-assigned structural key used to
    maintain balance, and left/right child pointers.
    """

    __slots__ = ("patient", "_balance_key", "left", "right")

    def __init__(self, patient: Patient) -> None:
        self.patient: Patient = patient
        # The balance key is assigned once at insertion and never changes.
        # It drives the heap-like structural invariant that keeps the tree
        # balanced in expectation without explicit rebalancing passes.
        self._balance_key: float = random.random()
        self.left: Optional[_Node] = None
        self.right: Optional[_Node] = None

    # Convenience aliases so callers can read node.acuity / node.patient_id
    # directly without going through node.patient each time.

    @property
    def acuity(self) -> int:
        return self.patient.acuity

    @property
    def patient_id(self) -> str:
        return self.patient.patient_id

    def __repr__(self) -> str:
        return f"_Node(acuity={self.acuity}, id={self.patient_id!r})"


# ---------------------------------------------------------------------------
# Patient store
# ---------------------------------------------------------------------------


class _AcuityIndex:
    """In-memory patient store ordered by acuity.

    Patients are kept in a tree ordered by acuity to support threshold
    partitioning.  The structural balance key stored in each node keeps the
    expected height at O(log n) without explicit rebalancing.  Alongside the
    tree the index keeps a tally of how many patients it holds at each acuity
    level, which answers counting queries without walking the tree.

    Patients with the same acuity are kept in order of insertion: a new
    patient goes behind those already stored at that level.  In the ascending
    sequence returned by inorder() that means the newest patient of a level
    comes first and the longest-standing one last, so maximum() returns the
    longest-standing patient of the highest level.

    Supported operations (n patients, expected time)
    ------------------------------------------------
    insert(patient)               O(log n)
    remove(patient_id)            O(n)      — full scan for the ID
    contains(patient_id)          O(n)
    find(patient_id)              O(n)
    maximum() / minimum()         O(log n)
    count_in_range(lo, hi)        O(1)      — read from the tally
    acuity_counts()               O(1)
    split_above(threshold)        O(log n)  — destructive partition
    merge_from(other)             O(log n)  — absorb another index
    inorder()                     O(n)
    """

    def __init__(self) -> None:
        self._root: Optional[_Node] = None
        self._count: int = 0
        self._tally: Dict[int, int] = {
            level: 0 for level in range(MIN_ACUITY, MAX_ACUITY + 1)
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def insert(self, patient: Patient) -> None:
        """Add *patient* to the index, behind any patients of equal acuity."""
        self._root = self._insert(self._root, patient)
        self._count += 1
        self._tally[patient.acuity] += 1

    def remove(self, patient_id: str) -> bool:
        """Remove the patient with the given ID.  Returns True if found."""
        new_root, removed = self._remove(self._root, patient_id)
        if removed is None:
            return False
        self._root = new_root
        self._count -= 1
        self._tally[removed.acuity] -= 1
        return True

    def contains(self, patient_id: str) -> bool:
        """Return True if a patient with *patient_id* is in the index."""
        return self._find_node(self._root, patient_id) is not None

    def find(self, patient_id: str) -> Optional[Patient]:
        """Return the Patient with the given ID, or None if absent."""
        node = self._find_node(self._root, patient_id)
        return node.patient if node else None

    def maximum(self) -> Optional[Patient]:
        """Return the longest-standing patient of the highest acuity, or None."""
        node = self._rightmost(self._root)
        return node.patient if node else None

    def minimum(self) -> Optional[Patient]:
        """Return the newest patient of the lowest acuity, or None."""
        node = self._leftmost(self._root)
        return node.patient if node else None

    def count_in_range(self, lo: int, hi: int) -> int:
        """Count patients whose acuity is in the closed interval [lo, hi].

        Answered from the per-level tally; the tree is not touched.  Returns 0
        if lo > hi.
        """
        return sum(n for level, n in self._tally.items() if lo <= level <= hi)

    def acuity_counts(self) -> Dict[int, int]:
        """Return the number of patients at each acuity level (1–10)."""
        return self._tally

    def split_above(self, acuity_threshold: int) -> "_AcuityIndex":
        """Destructively partition: remove and return patients with acuity >= threshold.

        After this call the current index retains only patients whose acuity
        is strictly below *acuity_threshold*.  The returned index holds all
        patients at or above the threshold.
        """
        below, above = self._partition(self._root, acuity_threshold)
        extracted = _AcuityIndex()
        extracted._root = above
        for level in extracted._tally:
            if level >= acuity_threshold:
                extracted._tally[level] = self._tally[level]
                self._tally[level] = 0
        extracted._count = sum(extracted._tally.values())
        self._root = below
        self._count -= extracted._count
        return extracted

    def merge_from(self, other: "_AcuityIndex") -> None:
        """Absorb all patients from *other* into this index, emptying *other*.

        Every patient in *other* must have strictly higher acuity than every
        patient currently in this index, as is the case when re-uniting the
        two halves produced by split_above().  Raises ValueError otherwise,
        leaving both indexes unchanged.
        """
        if self._root is not None and other._root is not None:
            if self._leftmost(other._root).acuity <= self._rightmost(self._root).acuity:
                raise ValueError(
                    "merge_from() requires every incoming patient to have "
                    "higher acuity than every patient already in the index."
                )
        self._root = self._merge(self._root, other._root)
        self._count += other._count
        for level, n in other._tally.items():
            self._tally[level] += n
        other._root = None
        other._count = 0
        other._tally = dict.fromkeys(other._tally, 0)

    def inorder(self) -> List[Patient]:
        """Return all patients sorted by acuity (ascending).

        Within one acuity level the most recently inserted patient comes first.
        """
        result: List[Patient] = []
        self._collect_inorder(self._root, result)
        return result

    def __len__(self) -> int:
        return self._count

    def __bool__(self) -> bool:
        return self._count > 0

    def __iter__(self) -> Iterator[Patient]:
        return iter(self.inorder())

    # ------------------------------------------------------------------
    # Core structural primitives
    # ------------------------------------------------------------------

    def _partition(
        self, node: Optional[_Node], threshold: int
    ) -> Tuple[Optional[_Node], Optional[_Node]]:
        """Split the subtree rooted at *node* into two disjoint subtrees.

        Returns (lower, upper) where:
            lower — patients with acuity <  threshold
            upper — patients with acuity >= threshold
        """
        if node is None:
            return None, None
        if node.acuity < threshold:
            lower, upper = self._partition(node.right, threshold)
            node.right = lower
            return node, upper
        else:
            lower, upper = self._partition(node.left, threshold)
            node.left = upper
            return lower, node

    def _merge(
        self, left: Optional[_Node], right: Optional[_Node]
    ) -> Optional[_Node]:
        """Merge two subtrees where no key in *left* is greater than any key
        in *right*.  All of *left* precedes all of *right* in the result; the
        balance keys determine the merged tree's shape."""
        if left is None:
            return right
        if right is None:
            return left
        if left._balance_key < right._balance_key:
            left.right = self._merge(left.right, right)
            return left
        else:
            right.left = self._merge(left, right.left)
            return right

    def _insert(self, node: Optional[_Node], patient: Patient) -> _Node:
        """Insert *patient* and return the new subtree root.

        The new node lands immediately before the existing nodes of the same
        acuity in the in-order sequence.
        """
        new_node = _Node(patient)
        lower, upper = self._partition(node, patient.acuity)
        return self._merge(self._merge(lower, new_node), upper)

    def _remove(
        self, node: Optional[_Node], patient_id: str
    ) -> Tuple[Optional[_Node], Optional[Patient]]:
        """Search for *patient_id* and remove it.

        Returns (new_root, removed_patient); removed_patient is None when the
        ID is not present, in which case the subtree is unchanged.
        """
        if node is None:
            return None, None
        if node.patient_id == patient_id:
            # Splice out by merging the two children directly.
            return self._merge(node.left, node.right), node.patient
        # The tree is ordered by acuity, not patient_id, so we must check
        # both subtrees.  Try left first; fall through to right if not found.
        new_left, removed = self._remove(node.left, patient_id)
        if removed is not None:
            node.left = new_left
            return node, removed
        new_right, removed = self._remove(node.right, patient_id)
        node.right = new_right
        return node, removed

    # ------------------------------------------------------------------
    # Traversal helpers
    # ------------------------------------------------------------------

    def _find_node(
        self, node: Optional[_Node], patient_id: str
    ) -> Optional[_Node]:
        """Full-tree search for a node by patient_id (O(n))."""
        if node is None:
            return None
        if node.patient_id == patient_id:
            return node
        found = self._find_node(node.left, patient_id)
        if found is not None:
            return found
        return self._find_node(node.right, patient_id)

    @staticmethod
    def _leftmost(node: Optional[_Node]) -> Optional[_Node]:
        if node is None:
            return None
        while node.left is not None:
            node = node.left
        return node

    @staticmethod
    def _rightmost(node: Optional[_Node]) -> Optional[_Node]:
        if node is None:
            return None
        while node.right is not None:
            node = node.right
        return node

    @staticmethod
    def _collect_inorder(node: Optional[_Node], out: List[Patient]) -> None:
        if node is None:
            return
        _AcuityIndex._collect_inorder(node.left, out)
        out.append(node.patient)
        _AcuityIndex._collect_inorder(node.right, out)
