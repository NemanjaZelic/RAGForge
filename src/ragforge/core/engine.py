"""One bundle engine selecting BM25, dense or RRF on the same sources."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ragforge.artifacts.verification import verify_bundle
from ragforge.core.contracts import (
    CollectionDescription,
    FetchContextRequest,
    RetrievalResponse,
    RetrievedChunk,
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
    from ragforge.core.source_context import SourceContext


class BundleEngine:
    def __init__(
        self,
        root: Path,
        *,
        threads: int = 4,
        source_context: Path | None = None,
        rerank_workers: int = 4,
        rerank_cache_batches: int = 512,
    ) -> None:
        self.root = root
        self.manifest = verify_bundle(root)
        self.collection = self.manifest.collections[0]
        self.sqlite = SQLiteEngine(root / self.collection.database_path)
        self._web_urls: dict[str, str] = {}
        if self.manifest.web_sources is not None:
            from ragforge.core.web_sources import read_web_sources

            self._web_urls = {
                item.source_path: item.url
                for item in read_web_sources(root / self.manifest.web_sources).sources
            }
        self._document_titles = {
            d.document_id: d.title for d in self.collection.documents if d.title
        }
        if type(rerank_workers) is not int or not 1 <= rerank_workers <= 8:
            raise ValueError("reranker workers must be between 1 and 8")
        self.threads = threads
        if type(rerank_cache_batches) is not int or not 0 <= rerank_cache_batches <= 4096:
            raise ValueError("reranker cache batches must be between 0 and 4096")
        self.rerank_workers = rerank_workers
        self.rerank_cache_batches = rerank_cache_batches
        self._source_context: SourceContext | None = None
        declared_context = self.manifest.source_context
        if declared_context is not None and source_context is not None:
            raise ValueError("choose inventoried or external source context, not both")
        if declared_context is not None or source_context is not None:
            from ragforge.core.source_context import SourceContext

            catalogue = root / declared_context if declared_context else source_context
            assert catalogue is not None
            checksum = next(
                r.sha256 for r in self.manifest.files if r.path == self.collection.database_path
            )
            self._source_context = SourceContext(
                catalogue,
                self.sqlite,
                checksum,
                self.collection.collection_id,
                verify=source_context is not None,
            )
        self._aliases: dict[str, str] = {}
        self._alias_scopes: dict[str, set[str]] = {}
        if (
            self.manifest.retrieval_configuration
            and self.manifest.retrieval_configuration.query_aliases
        ):
            from ragforge.core.aliases import read_aliases

            bank = read_aliases(self.root / self.manifest.retrieval_configuration.query_aliases)
            self._aliases = bank.mapping()
            document_ids = {d.source_path: d.document_id for d in self.collection.documents}
            self._alias_scopes = {
                d.short.casefold(): {document_ids[p.source_path] for p in d.proofs}
                for d in bank.definitions
            }
        self._reranker: ONNXReranker | None = None
        self._embedder: ONNXEmbedder | None = None
        self._dense: DenseStore | AnnStore | None = None
        self._parents: ParentMapper | None = None

    def _source_urls(self, response: RetrievalResponse) -> RetrievalResponse:
        if not self._web_urls:
            return response

        def annotated(items: list[RetrievedChunk]) -> list[RetrievedChunk]:
            result = []
            for item in items:
                url = self._web_urls.get(item.source.path)
                if url is None:
                    raise ValueError("returned source is missing its verified URL provenance")
                result.append(
                    item.model_copy(update={"source": item.source.model_copy(update={"url": url})})
                )
            return result

        return response.model_copy(
            update={"results": annotated(response.results), "context": annotated(response.context)}
        )

    def retrieve(self, request: RetrieveRequest) -> RetrievalResponse:
        config = self.manifest.retrieval_configuration
        if config and config.query_language == "en" and request.query_translation is not None:
            method = request.search_method or self.manifest.default_search_method
            if method != "hybrid" or request.rerank is False:
                raise ValueError(
                    "query translation requires hybrid retrieval with a local reranker"
                )
            # The explicitly declared English-docs profile uses the caller's
            # faithful source-language query. No translation service is called.
            request = request.model_copy(
                update={"query": request.query_translation, "query_translation": None}
            )
        response = self._retrieve(request)
        if self._source_context is not None:
            config = self.manifest.retrieval_configuration
            response = self._source_context.supplement(
                request,
                response,
                max_chunks_per_document=config.max_chunks_per_document if config else None,
            )
        config = self.manifest.retrieval_configuration
        method = request.search_method or self.manifest.default_search_method
        rerank = request.rerank if request.rerank is not None else method != "bm25"
        if config and config.section_context == "section-gaps-v3" and rerank:
            from ragforge.core.section_gaps import complete_section_gaps

            response = complete_section_gaps(
                self.sqlite,
                request,
                response,
                max_chunks_per_document=config.max_chunks_per_document,
                page_bounds=self._parents.page_range if self._parents is not None else None,
            )
        return self._source_urls(response)

    def _retrieve(self, request: RetrieveRequest) -> RetrievalResponse:
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
        if request.query_translation is not None:
            if config is None or method != "hybrid":
                raise ValueError(
                    "query translation requires hybrid retrieval with a local reranker"
                )
            from ragforge.core.translated import translated_response

            return translated_response(self, request)
        if config is not None and config.query_planning is not None and method == "hybrid":
            from ragforge.core.planning import planned_response

            return planned_response(self, request)
        ranking_query = (
            self._ranking_query(
                request.query, request.filters.document_ids if request.filters else None
            )
            if config is not None
            else request.query
        )
        lexical_request = request.model_copy(update={"query": ranking_query})
        if method == "bm25":
            if config is None:
                return self.sqlite.retrieve(request.model_copy(update={"search_method": "bm25"}))
            return self._rerank_response(
                self.sqlite.rank_bm25(lexical_request, config.candidates_per_method),
                request,
                method,
                ranking_query,
            )
        from ragforge.core.dense import CANDIDATES, reciprocal_rank_fusion

        parent_limit = (
            config.candidates_per_method
            if config is not None
            else (CANDIDATES if method == "hybrid" else request.top_k)
        )
        ranks = self._rank_dense(request, parent_limit)
        if method == "hybrid":
            ranks = reciprocal_rank_fusion(
                self.sqlite.rank_bm25(
                    lexical_request, config.candidates_per_method if config else CANDIDATES
                ),
                ranks,
                config.candidates_per_method * 2 if config else request.top_k,
            )
        if config is not None:
            return self._rerank_response(ranks, request, method, ranking_query)
        return self.sqlite.ranked_response(ranks, request, method)

    def _prepare_dense(self) -> None:
        from ragforge.core.dense import BACKEND, BACKEND_VERSION, DenseStore

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

                self._dense = AnnStore(
                    self.root / dense.path, dense_sqlite, model.dimensions, workers=self.threads
                )
            else:
                self._dense = DenseStore(self.root / dense.path, dense_sqlite, model.dimensions)

    def _rank_dense(self, request: RetrieveRequest, limit: int) -> list[tuple[str, float]]:
        self._prepare_dense()
        assert self._embedder is not None and self._dense is not None
        vector = self._embedder.encode([request.query], query=True)[0]
        filters = request.filters.document_ids if request.filters is not None else None
        ranks = self._dense.rank(vector, 200 if self._parents is not None else limit, filters)
        if self._parents is not None:
            ranks = self._parents.map_ranks(ranks, limit, filters)
        return ranks

    def _get_reranker(self) -> ONNXReranker:
        from ragforge.core.rerank import ONNXReranker

        if self._reranker is None:
            self._reranker = ONNXReranker(
                self.root / "models/reranker",
                threads=self.threads,
                workers=self.rerank_workers,
                cache_batches=self.rerank_cache_batches,
            )
        return self._reranker

    def warm_up(self) -> dict[str, bool]:
        """Explicit startup work; no document query or external model service."""
        method = self.manifest.default_search_method
        config = self.manifest.retrieval_configuration
        gpu = config is not None and config.reranker.runtime == "openvino-gpu-f16"
        dense = method in {"dense", "hybrid"}
        rerank = self.manifest.retrieval_configuration is not None and method != "bm25"
        if dense:
            self._prepare_dense()
            assert self._embedder is not None
            neutral = self._embedder.encode(["warmup"], query=True)[0]
            from ragforge.core.ann import AnnStore

            config = self.manifest.retrieval_configuration
            if (
                self._parents is not None
                and config
                and config.query_language == "en"
                and any(
                    d.source_path.casefold().endswith(".pdf") for d in self.collection.documents
                )
            ):
                self._parents.warm_up()
            if isinstance(self._dense, AnnStore) and not gpu:
                # Perform this after metadata scans so they cannot evict the
                # graph's common read paths immediately before the first query.
                self._dense.warm_up(neutral)
        if rerank:
            model = self._get_reranker()
            # Distinct neutral inputs prepare worker buffers, not a user-query cache.
            count = model.execution_batch_size * model.workers
            model.score(
                "warmup", [("warmup " + str(i) + " ") * model.spec.max_tokens for i in range(count)]
            )
        if dense and gpu:
            # GPU compilation and neutral shape preparation allocate shared RAM.
            # Touch graph pages afterwards so that allocation cannot immediately
            # evict the graph before the first novel query. No query cache.
            if isinstance(self._dense, AnnStore):
                self._dense.warm_up(neutral)
        return {"query_model": dense, "dense_index": dense, "reranker": rerank}

    def _ranking_query(self, query: str, allowed_documents: list[str] | None = None) -> str:
        from ragforge.core.aliases import expand_query

        aliases = self._aliases
        if allowed_documents is not None:
            allowed = set(allowed_documents)
            aliases = {
                key: value for key, value in aliases.items() if self._alias_scopes[key] & allowed
            }
        expanded = expand_query(query, aliases)
        if expanded == query:
            return query
        reranker = self._get_reranker()
        if len(reranker.tokenizer.encode(expanded).ids) > reranker.spec.max_tokens - 16:
            return query
        return expanded

    def _score_candidates(
        self,
        ranks: list[tuple[str, float]],
        request: RetrieveRequest,
        ranking_query: str | None = None,
    ) -> tuple[list[tuple[str, float]], dict[str, str]]:
        import json

        if not ranks:
            return [], {}
        reranker = self._get_reranker()
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
                prefix = source["path"] + "\n"
                title = self._document_titles.get(row["document_id"])
                if title is not None:
                    prefix += title + "\n"
                passages.append(prefix + (source.get("section") or "") + "\n" + row["text"])
                documents[key] = row["document_id"]
        scores = reranker.score(ranking_query or request.query, passages)
        ordered = sorted(
            zip((key for key, _ in ranks), scores, strict=True),
            key=lambda pair: (-pair[1], pair[0]),
        )
        return ordered, documents

    def _rerank_response(
        self,
        ranks: list[tuple[str, float]],
        request: RetrieveRequest,
        method: SearchMethod,
        ranking_query: str | None = None,
    ) -> RetrievalResponse:
        ordered, documents = self._score_candidates(ranks, request, ranking_query)
        return self._selected_response(ordered, documents, request, method)

    def _selected_response(
        self,
        ordered: list[tuple[str, float]],
        documents: dict[str, str],
        request: RetrieveRequest,
        method: SearchMethod,
    ) -> RetrievalResponse:
        config = self.manifest.retrieval_configuration
        assert config is not None
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
        response = self.sqlite.ranked_response(selected, request, method)
        if config.section_context is not None:
            from ragforge.core.sections import complete_sections

            return complete_sections(
                self.sqlite,
                request,
                response,
                max_chunks_per_document=config.max_chunks_per_document,
                policy="section-start-v2"
                if config.section_context == "section-gaps-v3"
                else config.section_context,
            )
        return response

    def fetch_context(self, request: FetchContextRequest) -> RetrievalResponse:
        return self._source_urls(self.sqlite.fetch_context(request))

    def list_collections(self) -> list[CollectionDescription]:
        return self.sqlite.list_collections()
