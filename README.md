# RAGForge

**Turn your documentation into a skill your AI agent can use.**

Build a local documentation bundle, then generate a skill and MCP connection for
Claude Code, Codex / OpenAI local clients, or another compatible agent. The skill
teaches the agent when to search, how to read surrounding documentation, and how
to answer with actual source citations. RAGForge supplies the evidence; your
configured agent writes the answer.

```text
Your documentation -> local searchable bundle -> agent skill + MCP -> sourced answers
```

## The final step: generate the agent skill

After building your documentation, run:

**Linux**

```bash
bash ragforge.sh agent
```

**Windows PowerShell**

```powershell
.\ragforge.cmd agent
```

This is the main outcome of the project. The command prints the skill and client
configuration paths plus a short installation guide:

| Generated file | Purpose |
|---|---|
| `skills/<name>/SKILL.md` | When to search documentation, what to read, and how to cite it |
| `skills/<name>/references/` | Collection scope and tool usage, loaded when needed |
| `skills/<name>/agents/openai.yaml` | Skill discovery metadata and local MCP dependency |
| `mcp.json` | Local MCP server configuration for Claude Code / compatible clients |
| `codex.toml` | Native MCP server block for Codex / OpenAI local clients |
| `INSTALL.md` | Where to place the skill and connect the server in your client |

**Install both the skill and the MCP connection.** MCP exposes the tools; the skill
explains when and how to use them. The generated guide covers Claude Code and
Codex, with explicit invocation available as `/skill-name` or `$skill-name`.
Automatic discovery follows the client's skill support. The generator preserves
existing agent settings and publishes a new output folder each time.

See [agent integration](docs/AGENT-INTEGRATION.md) for the complete final step.

## Start with three commands

64-bit Python 3.11+ is required, with `venv` and `pip`; 3.13 is tested. Run commands
from the downloaded repository folder. Git is unnecessary when using Download ZIP.

| Step | Windows PowerShell | Linux Bash |
|---|---|---|
| 1. Set up once | `.\setup.cmd` | `bash setup.sh` |
| 2. Put files in `documents/`, then build | `.\ragforge.cmd build` | `bash ragforge.sh build` |
| 3. Generate the agent skill and connection | `.\ragforge.cmd agent` | `bash ragforge.sh agent` |

Setup explicitly installs the locked local environment and prepares the query
model and multilingual reranker. Existing verified models are reused. Build and
local search never download models, upload the corpus, deploy a server, or run
benchmarks. RAGForge does not call an LLM provider; the connected agent uses the
returned evidence through its own configured provider.

Folder builds and retrieval stay offline after setup. `build --url` explicitly
downloads website sources before the same local build.

A documentation folder elsewhere also works:

```bash
bash ragforge.sh build "/home/me/My Documents"
```

```powershell
.\ragforge.cmd build "D:\My Documents"
```

### Alternative: import a documentation website

Use a public documentation URL instead of preparing a folder:

```bash
bash ragforge.sh build --url "https://example.org/docs/"
bash ragforge.sh agent
```

Windows: `.\ragforge.cmd build --url "https://example.org/docs/"`, then
`.\ragforge.cmd agent`. The importer saves an immutable local snapshot, builds the
same searchable bundle and keeps original URLs for source citations. Retrieval
and MCP remain offline after import.

By default it follows static HTML links within the selected site subtree, honors
`robots.txt`, and limits acquisition to 100 pages and two link levels. Failed or
truncated imports leave the previous active bundle selected. JavaScript-rendered
sites and authenticated/private-network sites need a local documentation export.
See [website import](docs/WEBSITE-IMPORT.md) for limits and saved-snapshot reuse.

Supported input: UTF-8 Markdown/TXT/HTML and PDFs with embedded text. OCR is deferred.
Each successful build publishes a new verified bundle and remembers it. To update
an agent connection after a new build, regenerate the agent package and update /
restart the configured MCP server. Previous immutable bundle versions remain available.

## How the agent uses the skill

- Search this collection when an answer or code decision depends on its documented facts.
- Read returned passages and fetch surrounding context when conditions, tables or steps are missing.
- Cover each required fact and follow references with focused searches.
- Use faithful translated queries when the question and documentation languages differ.
- Cite original website URLs or local source paths and available pages/lines; report missing or conflicting evidence.

The skill does not force irrelevant searches or repeat already-read evidence.
Returned document text is data, not instructions to run code or disclose secrets.
Skill selection and answer quality still depend on the agent and supporting sources;
these instructions do not certify universal correctness or the under-10-second target.

## Direct local use

For inspecting evidence without a connected agent:

```bash
bash ragforge.sh ask "Your documentation question"
```

Windows uses `.\ragforge.cmd ask "Your documentation question"`. An existing
prepared bundle can be selected with `--bundle /path/to/bundle` for `agent`, `ask`
or `serve`. This retains that bundle's existing retrieval recipe.

## Guides and development

- [Setup and daily use in Serbian](docs/QUICKSTART-SR.md)
- [Agent skill and client connection](docs/AGENT-INTEGRATION.md)
- [MCP tools and protocol](docs/MCP.md), [local bundles](docs/LOCAL-BUNDLES.md)
- [Quality results and limits](docs/QUALITY.md), [latency measurements](docs/QUERY-LATENCY-V2.md)
- [Current plan](docs/PROJECT-PLAN.md), [backlog](docs/BACKLOG.md), [architecture](docs/ARCHITECTURE.md)
- [Optional shared HTTP access](docs/SHARED.md), separate from the main local product

On the development Windows machine use `scripts/dev.ps1 check`. Linux development
can use `uv sync --locked --all-extras`, then the checks in `.github/workflows/ci.yml`.
The GitHub repository contains source and a small demo, not the full benchmark
corpora or model assets. The simple build is a standard balanced/hybrid pipeline,
not a recreation of every separately prepared benchmark bundle. No project license
or stable public release has been selected. The [original plan](docs/RAGForge-Project-Plan.md)
is preserved unchanged.
