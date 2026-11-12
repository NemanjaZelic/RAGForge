# Public VPS deployment and AI connection

## What the Ross comparison changed

AMD Ross separates the retrieval service from the answering model. Its local
quick start packages the stack behind a deployment command; the cloud-model
guide gives the client one MCP URL and a ready configuration. Its optional VS
Code extension bundles integration pieces. The transferable pattern is packaging
the server and client connection together, rather than asking the operator to
manually assemble authentication files and skills.

Sources reviewed on 2026-11-12:

- [AMD Ross quick start](https://github.com/Xilinx/ross-ai-assistant/blob/main/docs/local-kb/quickstart.md)
- [AMD Ross cloud-model connection](https://github.com/Xilinx/ross-ai-assistant/blob/main/docs/local-kb/frontier-model.md)
- [AnythingLLM Docker setup](https://docs.anythingllm.com/installation-docker/local-docker)
- [Open WebUI quick start](https://docs.openwebui.com/getting-started/quick-start/)
- [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https)
- [VS Code MCP installation links](https://code.visualstudio.com/api/extension-guides/ai/mcp)
- [Codex HTTP MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

## The simple public-server workflow

This route is for a VPS with Docker Compose and a public DNS domain. Complete
the existing setup/build flow first. Point the domain's A/AAAA records to that
VPS and allow inbound TCP 80 and 443. No manual TLS certificate is required.
The starter supports CPU bundles; Intel GPU reranker bundles require a separate
GPU-aware deployment.

On the VPS, from the repository folder with a ready bundle:

```bash
bash ragforge.sh publish --domain rag.example.com --start
```

The command asks for a password to encrypt the operator signing key, prepares a
new deployment directory, then explicitly builds/starts Docker. Initial container
build downloads base images and locked runtime dependencies. No LLM API key or
hosted answering model is required by this retrieval service.

To prepare on Windows or another machine without starting Docker:

```powershell
.\ragforge.cmd publish --domain rag.example.com --output deployments/public
```

Copy the generated folder to the VPS. From inside that folder:

```bash
docker compose -f compose.json up -d --build
```

`--bundle PATH` selects a previously prepared bundle. `--client ai-one --client
ai-two` creates separate client tokens. Existing deployment folders are never
overwritten. Starting Docker is explicit: omitting `--start` only creates files.

## Connect an AI client with the browser page

Open `https://rag.example.com/connect` and give each client only its own token
from the deployment's `clients/` directory:

1. Paste the token and click **Proveri vezu**. The page checks the permitted
   collections on this server.
2. Choose VS Code, Claude Code, Codex or another MCP client. VS Code has an
   installation button opening its normal MCP review screen. Other clients get
   downloadable/copyable configuration with specific placement instructions.
3. Download the skill archive and place `ragforge-docs/` in the indicated skill
   folder. Reopen the AI client as needed, confirm its MCP connection and ask a
   concrete documentation question.

The page is public static content containing no token or operator key. It does
not store tokens in browser storage; configuration previews mask them. Generated
client configuration DOES contain its token and must be kept private. The skill
archive has no credentials. Only a client application's supported integration can
install/enable MCP; a skill alone does not establish the network connection.

Client-format references:
[Claude MCP](https://code.claude.com/docs/en/mcp),
[VS Code MCP](https://code.visualstudio.com/docs/agent-customization/mcp-servers),
[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

## What runs on the server

```text
AI application -> HTTPS 443 -> Caddy -> loopback 8765 -> existing RAGForge engine
Browser        -> /connect -> public static connection page + credential-free skill
```

Caddy automatically obtains and renews certificates. Its data/configuration
volumes persist across restarts. RAGForge shares the gateway's network namespace
and binds only loopback; its backend port is never published. Both containers
restart unless stopped. The container uses the same locked Python runtime and
engine as the CLI. The bundle and policy are mounted read-only, while the signing
key and client token directory are neither mounted into containers nor included
in Docker's build context. Keep the deployment folder private on the host.

Document parsing and retrieval do not access the internet. Image/dependency
downloads and public certificate issuance/renewal are separate online deployment
operations. Caddy/TLS does not provision a VPS, domain, DNS record or firewall.

## Access and operation

This version retains existing RS256 JWT access and document grants. Tokens expire
after 60 minutes; automatic refresh and non-expiring API keys are not enabled.
To issue fresh client tokens from the source project:

```bash
bash ragforge.sh publish-renew --deployment /path/to/deployment
```

Enter the signing-key password and use the newly printed client folder. No
server restart is required for token renewal. Never distribute the signing key.
This is manual Bearer authentication rather than an interactive OAuth issuer.

For a new corpus version, prepare a new deployment and plan the replacement of
the running stack; there is no automatic public upgrade/rollback orchestration
in this starter. Existing local `deploy`/`activate`/`rollback` controls are
documented separately in [SHARED.md](SHARED.md).

Useful commands from a generated deployment folder:

```bash
docker compose -f compose.json ps
docker compose -f compose.json logs --tail=100
docker compose -f compose.json down
```

Do not remove the named volumes when stopping if certificate state must persist.

## Validation scope

Local tests validate copied bundle hashes, credential isolation, grants, generated
configuration/skill artifacts, unsafe inputs and explicit-start failure handling.
The skill passes the skill-creator validator. JavaScript configuration generation
is checked for the four supported client formats and masked previews.

The `docker-public` CI job runs the actual image, Caddy proxy, private-CA TLS and
authenticated retrieval on Linux. It uses Caddy's internal CA for its test DNS
name; real public ACME issuance still requires the operator's actual domain and
reachable ports. An unsuccessful or pending CI job is not evidence of a working
container deployment. Actual deployment to a user-owned VPS is a separate action.
