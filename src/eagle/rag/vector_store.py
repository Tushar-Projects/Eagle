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

    def _query_collection(
        self,
        query: str,
        where_clause: Optional[Dict[str, Any]],
        limit: int,
    ) -> List[SearchResult]:
        """Internal helper to execute a query against ChromaDB collection."""
        total_docs = self._collection.count()
        if total_docs == 0:
            return []

        actual_limit = min(limit, total_docs)
        if actual_limit <= 0:
            return []

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

    def search(
        self,
        query: str,
        run_id: Optional[str] = None,
        document_type: Optional[str] = None,
        knowledge_scope: Optional[str] = None,
        limit: int = 5,
    ) -> List[SearchResult]:
        """Perform semantic search over operational documents with knowledge-scope awareness.

        Semantics:
        - Unscoped query (run_id is None, knowledge_scope is None):
            Searches across both GLOBAL and RUN knowledge.
        - Explicit knowledge_scope (e.g. "GLOBAL" or "RUN"):
            Filters strictly by that knowledge scope.
        - Run-scoped query (run_id provided, knowledge_scope is None):
            Retrieves relevant documents matching:
                (knowledge_scope == "RUN" AND run_id == requested_run_id)
                OR
                (knowledge_scope == "GLOBAL")
            Executed as two controlled searches to ensure complete run isolation
            without relying on complex multi-clause Chroma filters.
        """
        total_docs = self._collection.count()
        if total_docs == 0:
            return []

        # Case 1: Explicit knowledge_scope requested
        if knowledge_scope == "GLOBAL":
            filters: List[Dict[str, Any]] = [{"knowledge_scope": "GLOBAL"}]
            if document_type:
                filters.append({"document_type": document_type})
            where = {"$and": filters} if len(filters) > 1 else filters[0]
            return self._query_collection(query, where, limit)

        if knowledge_scope == "RUN":
            filters = [{"knowledge_scope": "RUN"}]
            if run_id:
                filters.append({"run_id": run_id})
            if document_type:
                filters.append({"document_type": document_type})
            where = {"$and": filters} if len(filters) > 1 else filters[0]
            return self._query_collection(query, where, limit)

        # Case 2: Run-scoped query (run_id provided, knowledge_scope is None)
        if run_id:
            # Search 1: RUN-scoped documents for this specific run_id
            run_filters: List[Dict[str, Any]] = [
                {"knowledge_scope": "RUN"},
                {"run_id": run_id},
            ]
            if document_type:
                run_filters.append({"document_type": document_type})
            where_run = {"$and": run_filters}
            run_results = self._query_collection(query, where_run, limit)

            # Search 2: GLOBAL knowledge (learned rules)
            global_filters: List[Dict[str, Any]] = [{"knowledge_scope": "GLOBAL"}]
            if document_type:
                global_filters.append({"document_type": document_type})
            where_global = {"$and": global_filters} if len(global_filters) > 1 else global_filters[0]
            global_results = self._query_collection(query, where_global, limit)

            # Merge, deduplicate by document ID, and rank by semantic distance (ascending)
            seen_ids = set()
            combined: List[SearchResult] = []
            for item in run_results + global_results:
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    combined.append(item)

            combined.sort(key=lambda x: x.distance)
            return combined[:limit]

        # Case 3: Unscoped query (run_id is None, knowledge_scope is None)
        unscoped_filters: List[Dict[str, Any]] = []
        if document_type:
            unscoped_filters.append({"document_type": document_type})
        where_unscoped = (
            {"$and": unscoped_filters}
            if len(unscoped_filters) > 1
            else (unscoped_filters[0] if unscoped_filters else None)
        )
        return self._query_collection(query, where_unscoped, limit)

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
