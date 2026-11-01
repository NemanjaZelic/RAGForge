# Development fixtures

The mini-docs corpus was authored for this repository. It describes a fictional
service and intended retrieval behavior; it is not production documentation.

eval.jsonl contains exactly 20 draft development queries: 16 with authored
document relevance labels and 4 deliberately unsupported questions.
These are author-assigned labels, not independently reviewed user queries or
a held-out benchmark. No retrieval quality result has been measured yet.
The separate real-documentation benchmark is planned in
[docs/TESTING-PLAN.md](../docs/TESTING-PLAN.md); these fixtures do not replace it.

Each row contains query_id, collection_id, query, relevant_document_ids and kind.
Document IDs follow the algorithm in docs/ARCHITECTURE.md. File paths for reviewing
the labels are in relevant_source_paths. The evaluation loader should resolve IDs,
not treat paths as a second independent identity system.

Negative rows have an empty relevant_document_ids list. They must be reported
separately from recall/MRR. BM25 scores alone do not establish unanswerability.

The adversarial document is intentionally untrusted data. Its presence tests
retrieval boundaries later; it is not executable and is not copied into skills.

## Manifest contract fixtures

`manifests/minimal.json` and `manifests/balanced.json` are valid synthetic
contract examples. Repeated placeholder hashes, fixture backend/model identities
and sizes do not describe real files. No model/backend has been selected and
these examples cannot be searched or verified as a built bundle.
