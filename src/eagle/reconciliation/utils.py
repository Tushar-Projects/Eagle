"""Shared reconciliation utilities."""
import hashlib
from typing import List


def generate_relationship_id(source_ids: List[str], target_ids: List[str]) -> str:
    """Generate a stable, deterministic relationship ID using SHA-256.

    Inputs are sorted participant record IDs.
    This is the single canonical implementation used by both
    the deterministic engine and the AI classifier.
    """
    all_ids = sorted(source_ids + target_ids)
    joined = "|".join(all_ids)
    hash_hex = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return f"REL-{hash_hex[:12]}"
