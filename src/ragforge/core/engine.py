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

if TYPE_CHECKING:
    from ragforge.core.dense import DenseStore


class BundleEngine:
    def __init__(self, root: Path, *, threads: int = 4) -> None:
        self.root = root
        self.manifest = verify_bundle(root)
        self.collection = self.manifest.collections[0]
        self.sqlite = SQLiteEngine(root / self.collection.database_path)
        self.threads = threads
        self._embedder: ONNXEmbedder | None = None
        self._dense: DenseStore | None = None

    def retrieve(self, request: RetrieveRequest) -> RetrievalResponse:
        method = request.search_method or self.manifest.default_search_method
        if method not in self.manifest.capabilities:
            raise ValueError("search method is unsupported by this bundle profile")
        if request.collection_id not in (None, self.collection.collection_id):
            raise ValueError("unknown collection")
        if method == "bm25":
            return self.sqlite.retrieve(request.model_copy(update={"search_method": "bm25"}))
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
        if (dense.backend, dense.backend_version, dense.metric) != (
            BACKEND,
            BACKEND_VERSION,
            "cosine",
        ):
            raise ValueError("unsupported dense backend/version/metric")
        if model.runtime != "onnxruntime-cpu":
            raise ValueError("unsupported local query runtime")
        if self._embedder is None:
            self._embedder = ONNXEmbedder(self.root / "models/query", threads=self.threads)
        if self._dense is None:
            self._dense = DenseStore(
                self.root / dense.path, self.sqlite, self._embedder.spec.dimensions
            )
        vector = self._embedder.encode([request.query], query=True)[0]
        filters = request.filters.document_ids if request.filters is not None else None
        ranks = self._dense.rank(
            vector, CANDIDATES if method == "hybrid" else request.top_k, filters
        )
        if method == "hybrid":
            ranks = reciprocal_rank_fusion(
                self.sqlite.rank_bm25(request, CANDIDATES), ranks, request.top_k
            )
        return self.sqlite.ranked_response(ranks, request, method)

    def fetch_context(self, request: FetchContextRequest) -> RetrievalResponse:
        return self.sqlite.fetch_context(request)

    def list_collections(self) -> list[CollectionDescription]:
        return self.sqlite.list_collections()
