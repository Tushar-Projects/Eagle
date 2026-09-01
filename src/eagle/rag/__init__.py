"""Eagle RAG and Q&A package."""

from eagle.rag.document_builder import DocumentBuilder
from eagle.rag.models import (
    QARequest,
    QAResponse,
    RagDocument,
    SearchResult,
    SourceAttribution,
)
from eagle.rag.qa_agent import EagleQAAgent
from eagle.rag.qa_provider import (
    LlamaServerQAProvider,
    MockQAProvider,
    QAProvider,
    get_qa_provider,
)
from eagle.rag.vector_store import EagleVectorStore

__all__ = [
    "DocumentBuilder",
    "EagleQAAgent",
    "EagleVectorStore",
    "LlamaServerQAProvider",
    "MockQAProvider",
    "QAProvider",
    "QARequest",
    "QAResponse",
    "RagDocument",
    "SearchResult",
    "SourceAttribution",
    "get_qa_provider",
]
