# Search within an explicitly named document

When a question is about one particular document, put its exact indexed
**top-level heading** on the final query line. For example:

```json
{
  "query": "Which retry conditions apply?\nDocument title: Amber Protocol",
  "search_method": "hybrid",
  "top_k": 50,
  "max_output_chars": 48000
}
```

`Paper title:` is an alias for `Document title:`. Keep the actual title, including
its version, unchanged. The engine looks up a literal title phrase in the existing
FTS index and verifies it against the first indexed heading. Exactly one matching
document inside the caller's existing `filters.document_ids` grant is required.
Only then does the engine rank the question without its title within that source.
The source/document IDs come from the verified index, never a benchmark answer map.
Body references and nested headings cannot establish a document title.

Unknown titles, duplicate titles, multiple title markers and exhausted candidate
limits preserve the original collection search. The lookup accepts 2-48 title
words and at most 512 title characters, examines at most 64 returned candidates,
and falls back when the 65-candidate boundary is reached. It uses no network,
generated answer, new model, source-file execution or index rebuild. This does not
add a new request field or change the CLI/MCP/HTTP schema.

Queries without an explicit marker keep the existing retrieval path. Do not add
a title for cross-document comparisons or guess a title from a filename. If the
question cannot be answered from the named document, report the gap or perform
an explicitly broader search rather than assume its contents.

For a request that uses a separate `query_translation`, both question strings
must declare the same exact title. The title is not translated. Matching markers
are removed from both ranking questions after successful resolution; missing or
conflicting translated scopes preserve ordinary translated retrieval. An explicit
English-query bundle already selects its caller-supplied English query first.
The runtime performs no automatic translation.

The provider-neutral generated agent skill teaches this workflow. Regenerate the
agent package with the existing agent command after updating the application.
Existing bundles work without rebuilding. Returned text still supplies the
answer; resolving the right title alone never establishes a fact.

## Why separate title and question?

A long title can dominate lexical candidates and cross-encoder relevance for a
short question such as a request for evaluation data. Using that title as explicit
source scope lets ranking focus on the question. This is an intentional change
from global title-plus-question retrieval to source-confirmed document retrieval,
not a claim that both protocols are identical. Quality and speed results are
reported separately from the original untouched T8 first test.

The [validation protocol](benchmarks/title-scope-validation-protocol-v1.json)
freezes 120 previously unused questions from 120 papers disjoint from the
original T8 sample, within the same QASPER corpus. It is published before the
validation requests. It does not establish all-language or 3GPP-scale quality.
