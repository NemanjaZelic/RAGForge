# Offline retrieval

## Minimal profile
The minimal retrieval profile uses SQLite FTS5 and BM25.
It does not need an embedding model, a GPU, Docker or an external LLM API.

## Network policy
A local query opens the installed bundle and returns source snippets.
It must not download models, send telemetry or open a listening HTTP port.
Missing dependencies are reported as errors instead of triggering a network fallback.

## Data and runtime
A data bundle can move to another directory without rebuilding its embeddings.
The receiving computer still needs a compatible retrieval runtime.
