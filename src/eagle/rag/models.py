"""Data models for Eagle's grounded RAG and Q&A layer."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RagDocument(BaseModel):
    """Normalized document prepared for vector indexing and semantic retrieval."""
    id: str
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """Result retrieved from vector storage with distance/similarity score."""
    id: str
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    distance: float = 0.0


class SourceAttribution(BaseModel):
    """Explicit grounded source citation for Q&A responses."""
    document_type: str
    identifier: str
    title: str
    snippet: str
    run_id: Optional[str] = None
    relationship_id: Optional[str] = None
    rule_id: Optional[str] = None
    correction_id: Optional[str] = None


class QARequest(BaseModel):
    """Request schema for asking grounded operational questions."""
    question: str
    run_id: Optional[str] = None
    max_sources: int = 5


class QAResponse(BaseModel):
    """Response schema containing grounded answers and traceable source citations."""
    question: str
    answer: str
    sources: List[SourceAttribution] = Field(default_factory=list)
    run_id: Optional[str] = None
    has_sufficient_evidence: bool = True
    retrieval_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
