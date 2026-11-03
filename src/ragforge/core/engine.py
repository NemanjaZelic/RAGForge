"""One bundle engine selecting BM25, dense or RRF on the same sources."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ragforge.artifacts.verification import verify_bundle
from ragforge.core.contracts import (
    CollectionDescription,
    FetchContextRequest,
    RetrievalResponse,
    RetrieveRequest,
)
from ragforge.core.embedding import ONNXEmbedder
from ragforge.core.sqlite import SQLiteEngine
from ragforge.types import SearchMethod

if TYPE_CHECKING:
    from ragforge.core.ann import AnnStore
    from ragforge.core.dense import DenseStore
    from ragforge.core.parents import ParentMapper
    from ragforge.core.rerank import ONNXReranker


class BundleEngine:
    def __init__(self, root: Path, *, threads: int = 4) -> None:
        self.root = root
        self.manifest = verify_bundle(root)
        self.collection = self.manifest.collections[0]
        self.sqlite = SQLiteEngine(root / self.collection.database_path)
        self.threads = threads
        self._reranker: ONNXReranker | None = None
        self._embedder: ONNXEmbedder | None = None
        self._dense: DenseStore | AnnStore | None = None
        self._parents: ParentMapper | None = None

    def retrieve(self, request: RetrieveRequest) -> RetrievalResponse:
        method = request.search_method or self.manifest.default_search_method
        if method not in self.manifest.capabilities:
            raise ValueError("search method is unsupported by this bundle profile")
        if request.collection_id not in (None, self.collection.collection_id):
            raise ValueError("unknown collection")
        config = self.manifest.retrieval_configuration
        use_reranker = (
            request.rerank
            if request.rerank is not None
            else (config is not None and method != "bm25")
        )
        if use_reranker and config is None:
            raise ValueError("reranking requires a bundle with a local reranker")
        if not use_reranker:
            config = None
        if method == "bm25":
            if config is None:
                return self.sqlite.retrieve(request.model_copy(update={"search_method": "bm25"}))
            return self._rerank_response(
                self.sqlite.rank_bm25(request, config.candidates_per_method), request, method
            )
        from ragforge.core.dense import (
            BACKEND,
            BACKEND_VERSION,
            CANDIDATES,
            DenseStore,
            reciprocal_rank_fusion,
        )

        dense = self.collection.dense_index
        model = self.manifest.query_model
        if dense is None or model is None:
            raise ValueError("dense/hybrid requires a local query model and dense index")
        from ragforge.core.ann import BACKEND as ANN_BACKEND
        from ragforge.core.ann import BACKEND_VERSION as ANN_VERSION

        backend = (dense.backend, dense.backend_version)
        if dense.metric != "cosine" or backend not in {
            (BACKEND, BACKEND_VERSION),
            (ANN_BACKEND, ANN_VERSION),
        }:
            raise ValueError("unsupported dense backend/version/metric")
        if model.runtime != "onnxruntime-cpu":
            raise ValueError("unsupported local query runtime")
        if self._embedder is None:
            self._embedder = ONNXEmbedder(self.root / "models/query", threads=self.threads)
        if self._dense is None:
            dense_sqlite = self.sqlite
            if dense.source_chunks is not None:
                from ragforge.core.parents import ParentMapper

                dense_sqlite = SQLiteEngine(self.root / dense.source_chunks.database_path)
                self._parents = ParentMapper(dense_sqlite, self.sqlite)
            if backend == (ANN_BACKEND, ANN_VERSION):
                from ragforge.core.ann import AnnStore

                self._dense = AnnStore(self.root / dense.path, dense_sqlite, model.dimensions)
            else:
                self._dense = DenseStore(self.root / dense.path, dense_sqlite, model.dimensions)
        vector = self._embedder.encode([request.query], query=True)[0]
        filters = request.filters.document_ids if request.filters is not None else None
        parent_limit = (
            config.candidates_per_method
            if config is not None
            else (CANDIDATES if method == "hybrid" else request.top_k)
        )
        ranks = self._dense.rank(
            vector, 200 if self._parents is not None else parent_limit, filters
        )
        if self._parents is not None:
            ranks = self._parents.map_ranks(ranks, parent_limit, filters)
        if method == "hybrid":
            ranks = reciprocal_rank_fusion(
                self.sqlite.rank_bm25(
                    request, config.candidates_per_method if config else CANDIDATES
                ),
                ranks,
                config.candidates_per_method * 2 if config else request.top_k,
            )
        if config is not None:
            return self._rerank_response(ranks, request, method)
        return self.sqlite.ranked_response(ranks, request, method)

    def _rerank_response(
        self, ranks: list[tuple[str, float]], request: RetrieveRequest, method: SearchMethod
    ) -> RetrievalResponse:
        import json

        from ragforge.core.rerank import ONNXReranker

        config = self.manifest.retrieval_configuration
        assert config is not None
        if not ranks:
            return RetrievalResponse(contract_version="1", results=[])
        if self._reranker is None:
            self._reranker = ONNXReranker(self.root / "models/reranker", threads=self.threads)
        passages = []
        documents = {}
        with self.sqlite._connect() as connection:
            for key, _ in ranks:
                row = connection.execute("SELECT * FROM chunks WHERE chunk_id=?", (key,)).fetchone()
                if row is None:
                    raise ValueError("reranker candidate missing")
                if request.filters and row["document_id"] not in request.filters.document_ids:
                    raise ValueError("reranker candidate outside document scope")
                source = json.loads(row["source_json"])
                passages.append(
                    source["path"] + "\n" + (source.get("section") or "") + "\n" + row["text"]
                )
                documents[key] = row["document_id"]
        scores = self._reranker.score(request.query, passages)
        ordered = sorted(
            zip((key for key, _ in ranks), scores, strict=True),
            key=lambda pair: (-pair[1], pair[0]),
        )
        selected = []
        counts: dict[str, int] = {}
        for key, score in ordered:
            doc = documents[key]
            if (
                config.max_chunks_per_document is not None
                and counts.get(doc, 0) >= config.max_chunks_per_document
            ):
                continue
            counts[doc] = counts.get(doc, 0) + 1
            selected.append((key, score))
            if len(selected) == request.top_k:
                break
        return self.sqlite.ranked_response(selected, request, method)

    def fetch_context(self, request: FetchContextRequest) -> RetrievalResponse:
        return self.sqlite.fetch_context(request)

    def list_collections(self) -> list[CollectionDescription]:
        return self.sqlite.list_collections()
