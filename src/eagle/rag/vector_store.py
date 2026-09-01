"""ChromaDB vector store integration for Eagle operational knowledge."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from eagle.core.config import Settings
from eagle.rag.document_builder import DocumentBuilder
from eagle.rag.models import RagDocument, SearchResult
from eagle.storage.repository import Repository

logger = logging.getLogger(__name__)

COLLECTION_NAME = "eagle_operational_knowledge"


class EagleVectorStore:
    """Manages ChromaDB collections, idempotent document indexing, and semantic retrieval."""

    def __init__(self, chroma_path: str = "./chroma_data", client: Optional[ClientAPI] = None):
        self.chroma_path = chroma_path
        if client is not None:
            self._client = client
        elif chroma_path == ":memory:":
            self._client = chromadb.EphemeralClient()
        else:
            p = Path(chroma_path)
            p.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(p.resolve()))

        self._collection: Collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def collection(self) -> Collection:
        return self._collection

    def count(self) -> int:
        """Return the number of indexed documents."""
        return self._collection.count()

    def add_documents(self, documents: List[RagDocument]) -> int:
        """Idempotently add or update documents in the collection."""
        if not documents:
            return 0

        ids = [doc.id for doc in documents]
        texts = [doc.text for doc in documents]
        # Clean metadata for ChromaDB (no None values, only primitives)
        metadatas = []
        for doc in documents:
            clean_meta = {}
            for k, v in doc.metadata.items():
                if v is None:
                    continue
                if isinstance(v, (str, int, float, bool)):
                    clean_meta[k] = v
                else:
                    clean_meta[k] = str(v)
            metadatas.append(clean_meta)

        self._collection.upsert(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
        )
        return len(documents)

    def search(
        self,
        query: str,
        run_id: Optional[str] = None,
        document_type: Optional[str] = None,
        limit: int = 5,
    ) -> List[SearchResult]:
        """Perform semantic search over operational documents with optional metadata filtering."""
        where_clause: Optional[Dict[str, Any]] = None

        filters = []
        if run_id:
            filters.append({"run_id": run_id})
        if document_type:
            filters.append({"document_type": document_type})

        if len(filters) == 1:
            where_clause = filters[0]
        elif len(filters) > 1:
            where_clause = {"$and": filters}

        total_docs = self._collection.count()
        if total_docs == 0:
            return []

        actual_limit = min(limit, total_docs)

        query_kwargs: Dict[str, Any] = {
            "query_texts": [query],
            "n_results": actual_limit,
        }
        if where_clause:
            query_kwargs["where"] = where_clause

        try:
            results = self._collection.query(**query_kwargs)
        except Exception as e:
            logger.warning("Vector search query error with filter %s: %s", where_clause, e)
            return []


        search_results: List[SearchResult] = []
        if not results or not results["ids"] or not results["ids"][0]:
            return search_results

        ids = results["ids"][0]
        documents = results["documents"][0] if results.get("documents") else [""] * len(ids)
        metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(ids)
        distances = results["distances"][0] if results.get("distances") else [0.0] * len(ids)

        for doc_id, text, meta, dist in zip(ids, documents, metadatas, distances):
            search_results.append(
                SearchResult(
                    id=doc_id,
                    text=text,
                    metadata=meta,
                    distance=float(dist) if dist is not None else 0.0,
                )
            )

        return search_results

    def index_run(self, repository: Repository, run_id: str, metrics: Optional[dict] = None) -> int:
        """Index all operational entities for a run into ChromaDB."""
        run = repository.get_run(run_id)
        if not run:
            logger.warning("Cannot index non-existent run %s", run_id)
            return 0

        docs: List[RagDocument] = []

        # 1. Run Document
        docs.append(DocumentBuilder.build_run_document(run, metrics))

        # 2. Results Documents with Participating Records
        results = repository.get_results(run_id)
        source_records_list = repository.get_records(run_id, source="GATEWAY")
        target_records_list = repository.get_records(run_id, source="BANK")

        source_lookup = {r.record_id: r for r in source_records_list}
        target_lookup = {r.record_id: r for r in target_records_list}

        for r in results:
            docs.append(DocumentBuilder.build_result_document(run_id, r, source_lookup, target_lookup))

        # 3. Operator Corrections
        corrections = repository.get_corrections(run_id)
        for c in corrections:
            docs.append(DocumentBuilder.build_correction_document(c))

        # 4. Learned Rules
        rules = repository.get_rules(active_only=False)
        for rule in rules:
            docs.append(DocumentBuilder.build_rule_document(rule))

        # 5. Audit Log Events
        audit_logs = repository.get_audit_logs(run_id)
        for a in audit_logs:
            doc = DocumentBuilder.build_audit_document(run_id, a)
            if doc:
                docs.append(doc)

        return self.add_documents(docs)

    def delete_run(self, run_id: str) -> None:
        """Delete all documents associated with a specific run."""
        try:
            self._collection.delete(where={"run_id": run_id})
        except Exception as e:
            logger.warning("Error deleting vector documents for run %s: %s", run_id, e)
