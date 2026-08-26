"""String normalization for deterministic matching (Stage 2)."""
import re

def normalize_reference(ref: str | None) -> str:
    """Deterministically normalize a reference string for Stage 2 matching.
    
    Standardizes case (lowercase), strips surrounding whitespace, and removes
    common separators (-, _) to enable conservative fuzzy matching.
    """
    if not ref:
        return ""
    
    # 1. Lowercase
    normalized = ref.lower()
    
    # 2. Strip surrounding whitespace
    normalized = normalized.strip()
    
    # 3. Remove common separators
    normalized = re.sub(r'[-_]', '', normalized)
    
    return normalized
