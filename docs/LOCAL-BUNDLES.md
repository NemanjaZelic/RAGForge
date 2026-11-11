# Local balanced bundle implementation

RF-009, RF-004 and the local RF-005 build/use path are implemented together.
The representative test-set work is separate and was not modified here.
This is a pre-release implementation; broader quality gates remain RF-006.

## Model and runtime

The initial multilingual candidate is intfloat/multilingual-e5-small at
614241f622f53c4eeff9890bdc4f31cfecc418b3, using its upstream quantized
onnx/model_qint8_avx512_vnni.onnx graph. The pinned public model card declares
MIT; its card and upstream license text are copied unchanged into the package.
The model license does not select a license for RAGForge or user corpora.

The comparison candidate was sentence-transformers/all-MiniLM-L6-v2 at
1110a243fdf4706b3f48f1d95db1a4f5529b4d41 (quint8 AVX2, Apache-2.0).
[Measured implementation pilot](benchmarks/model-runtime-pilot.json) records
both real models, graph checksums, package bytes, runtime versions and all
BM25/dense/hybrid results on the same existing 20 development questions.
Both score 1.0 on the coarse positive document labels; this does not choose
a quality winner. Dense/hybrid return results for all 4 unanswerable queries.
There is no calibrated abstention threshold or held-out quality claim.

The initial multilingual choice accepts a larger package (about 136 MB vs
24 MB) and slower cold start. Existing tiny-corpus timings are observations
on this CPU, not a general speed promise. External test sets may change the
selection. Model card sources:
[intfloat](https://huggingface.co/intfloat/multilingual-e5-small),
[MiniLM](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2).

Balanced optional dependencies are CPU ONNX Runtime, NumPy and Tokenizers.
No Torch, GPU, model hub client calls, model download or HTTP server is
needed in inference. Only local Tokenizer.from_file and an explicit CPU
InferenceSession are used; ONNX Runtime telemetry is disabled before session
creation. Graphs are loaded from bounded bytes, with no filesystem base for
external weights. Inputs are tokenized with the model's recorded prefixes,
masked mean pooled and L2 normalized. Oversized token inputs fail clearly;
they are never silently truncated. Max graph size is 256 MiB.

## One retrieval contract

SQLite still holds the source text and metadata. An embedded NumPy v1.0
little-endian float32 matrix stores normalized embeddings in sorted chunk_id
order. Shape, row count, byte size and dimensions must match the same DB
and local model. Dense load rejects pickle/object arrays and nonfinite or
non-normalized vectors. The supported backend format is numpy-exact-cosine v1.

This is exact cosine search, not ANN: query work grows with chunk count.
Supported dense indexes have 1-100000 rows and the package model's dimensions.
Block scans limit temporary vectors; the index is read-only memory mapped.
This is a bounded data format, not a hard OS RAM/CPU sandbox for hostile models.

RRF uses up to 50 candidates per branch and k=60, with 1-based ranks.
It fuses ranks, not incomparable BM25/cosine scores. Ties use chunk_id.
Both branches apply the same collection and document filters. The same
source IDs, text, page/line citations and output limits are used for all
methods. Context remains a same-document, bounded, unranked operation.

A balanced bundle defaults to hybrid; minimal defaults to BM25.
Explicit BM25 on balanced never imports NumPy/ONNX/Tokenizers, creates a
model session or loads a dense matrix. Full integrity verification still
streams through the model files to check checksums, so cold verification
has I/O cost. Missing/corrupt model files or an unsupported method are errors;
there is no silent download or fallback.

## Source filename case

Source paths preserve case. On a filesystem that supports distinct entries such
as `readme.txt` and `Readme.txt` (including case-distinct directories), each is
indexed separately with its own document ID and exact source citation. No input
file is renamed or merged. This supersedes the earlier source casefold-collision
restriction in the architecture notes.

The bundle stores source paths as metadata and text in SQLite, so it can be
searched on Windows without recreating those original source files. Copying the
raw source corpus to a case-insensitive filesystem still requires distinct names.
Physical bundle and model files retain portable, case-insensitive inventory
checks; exact duplicate source paths remain invalid.

## Data package, integrity and publication

Build is local/offline and requires an explicitly prepared model directory
for balanced. Minimal packages only SQLite. Balanced adds dense.index and
models/query with the graph, tokenizer, model descriptor and license/card.
No Python interpreter or universal binary environment is bundled.

The manifest inventories every data file with SHA-256 and size, source
document identities/content hashes, parser/chunker versions/configuration,
PDF options, model revision/dimensions/license and runtime/backend versions.
NOASSERTION records that the RAGForge and user corpus licenses are unspecified.

Verification rejects unsupported artifact/DB/model/dense versions, traversal,
nonportable/colliding paths, links/reparse points, extra/missing files or
empty directories, mismatched build identity and content hashes, and
inconsistent SQLite/model/dense metadata. Inventory is checked before DB
or model use. Checksum integrity does not authenticate the author or make
an arbitrary malicious SQLite/ONNX package trusted.

Limits: manifest 32 MiB, inventory 10000 entries, file 2 GiB, total 4 GiB.
The current builder's dense model limit is narrower than the file cap.
Source/parse/index limits continue to apply. Bundle output must be outside
the corpus; empty/no-searchable-text builds fail. Incomplete PDF indexing
requires an explicit option and carries its reports forward.

Build writes to an owned sibling staging directory, closes all data files,
verifies the result and atomically publishes a new directory. Existing
versions are never replaced, including a racing empty directory.
Windows uses non-replacing rename; Linux uses renameat2(RENAME_NOREPLACE).
Other build OSes currently fail explicitly. Failed builds clean up only
the checked, owned staging path. This is atomic visibility, not a power-loss
durability or cryptographic-signature guarantee.

## CLI

Network provisioning is explicit maintenance, outside build/query:

```powershell
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 run python scripts/prepare_models.py e5-small models/e5-small
.\scripts\dev.ps1 run ragforge build examples/mini-docs --output kb/mini-v1 --model models/e5-small --collection mini --offline
.\scripts\dev.ps1 run ragforge verify kb/mini-v1
.\scripts\dev.ps1 run ragforge use kb/mini-v1 --mode local --query "How are access tokens sent?"
.\scripts\dev.ps1 run ragforge use kb/mini-v1 --query rollback --search-method bm25
.\scripts\dev.ps1 run ragforge context kb/mini-v1 CHUNK_ID
```

Choose a new output directory for the next version. Compute/mode values
other than local are rejected before action. No deployment follows build.
Existing standalone index/search commands remain available.

Tests cover real ONNX execution, ranking/filter/output bounds, relocation,
BM25 without ML imports, corruption/false inventories, no-replace races,
failure cleanup and socket/DNS-blocked build/use. CI adds the selected real
pretrained model on Windows/Linux and an OS network namespace on Linux.
No representative corpora, golden questions or final holdout were created.
