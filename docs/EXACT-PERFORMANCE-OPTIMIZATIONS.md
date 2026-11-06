# Runtime overhead optimizations

Status: prepared on `perf/exact-runtime-overhead`, separately from the frozen
3GPP evaluation. Its running source snapshots, model, candidate pool, request
limits, inputs and saved outputs stay unchanged. No benchmark restart.

## Implemented: cheaper exact storage accounting

`StorageBudget` now traverses with fresh `os.scandir` entries and reads their
non-following metadata directly. Windows directory enumeration already supplies
most of this metadata; constructing a Path and issuing lstat for every file was
unnecessary. Every directory is checked again before descent. The traversal
counts logical file sizes separately for each path, including identical files;
it never excludes benchmark output directories or substitutes allocated disk size.

The 30-second refresh interval, `.account`, planned allocation, byte limits and
physical free-space reserve remain unchanged. Links/reparse points and metadata
or directory read failures abort accounting. A changing filesystem is not a
transactional snapshot; this remains an application budget, not an OS quota.
The fresh DirEntry metadata is discarded after each refresh.

Observed whole benchmark tree scan: original 6.961 s, optimized 1.460 s.
These are separate single observations while the evaluation runs and files grow,
not a controlled end-to-end comparison. A paired scan of the retained 3GPP input
tree counts exactly 3,565,090,422 bytes with both implementations: original
1.447 s, optimized 0.458 s. Original ran first; OS caches were not cleared.
Do not turn these component ratios into a claim that queries are 3–5 times faster.

[Python PEP 471](https://peps.python.org/pep-0471/) documents the Windows metadata
reuse and why long-lived DirEntry objects must not substitute for fresh stats.
Numeric observations and scope: [runtime overhead report](benchmarks/exact-runtime-overhead-v1.json).

## Next experiments, in priority order

| Change | Evidence / expected role | Acceptance before adoption |
|---|---|---|
| Bounded exact PDF page ordinal-range cache | Existing read-only prototype: 2.485 s to 1.302 s for 140 actual child candidates / 35 pages; all 80 mapped outputs identical. Small component gain. | Retain document/page predicate, full eligible text, original ordering, grants, all row/character/cache limits; test null pages, repeated pages, eviction, missing metadata and fallback. |
| Combine ANN SQLite metadata lookups across shards | Lookups are already batched within each shard. Cross-shard batching could reduce remaining SQL overhead; benefit unmeasured. | Still validate every candidate key and vector, preserve per-shard floating-point calculations, all mappings, score and chunk-ID tie ordering; bounded buffers and SQL parameter batches. No skipping integrity checks for losing candidates. |
| Reuse exact intermediate results across control methods | Hybrid and dense controls may repeat embeddings or dense retrieval; literal full-query duplicates are only 17/1,322. Cache scope must be measured first. | Bounded memory/disk, key includes exact effective query, model/index identity, runtime/configuration, document filters and request/grant boundaries. Preserve candidates and result order. ANN search at a larger limit cannot be assumed to have the same prefix as a smaller search. |
| CPU thread count and inference batching | Representative 200-pair reranking took 35.895 s on two threads, batch eight; this is the largest observed component. Thread oversubscription can negate gains. No new neural profiling while this run competes for CPU. | Fixed models and all candidates; compare actual token inputs, scores, final ordering and complete returned evidence on EN/SR variants and difficult cases. Different quantized batch shapes or padding can change numbers, so this is not yet a lossless optimization. |
| Length bucketing / GPU inference | Could reduce padding or inference time, but provider support, performance and parity have not been established locally. GPU backend is not installed. | Separate experiment after the frozen run; token/truncation parity, ordering and full evidence regression required. No provider installation or CPU-only release-scope change as a side effect. |

Candidate reduction (200 to 50), shorter passage limits, another model and early
reranking exits are quality/speed tradeoffs, not exact-overhead changes. They
remain outside this optimization. Current quality results must finish with the
frozen settings first.

Storage accounting cannot change rankings because it does not feed retrieval.
Its tests cover nested logical bytes, identical content at different paths,
allocation and free-space guards, refresh and explicit refresh, permissions,
vanished files, symlinks and Windows reparse metadata. The whole local software
suite and CI are recorded with the change; timing probes are not quality scores.
