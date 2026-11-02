# Shared REST and MCP HTTP

Status: RF-010A transport/access control and local RF-010B version controls are
implemented. A systemd example is provided; actual host rollout, backup automation
and multi-device deployment remain operator/infrastructure work. No remote host, provider or identity account is created by these commands.
The default remains local CLI/stdio. One process binds one immutable collection.

## Use the same bundle

Install the optional `shared` extra. It includes the MCP SDK, Uvicorn and offline
JWT cryptography. The HTTP adapter uses the SDK's existing Starlette ASGI app for
thin REST routes, avoiding another web framework and a second retrieval engine.
BM25/dense/hybrid and context use the same contracts, IDs and output bounds as CLI
and stdio; switching transport does not reindex the bundle.

```powershell
.\scripts\dev.ps1 run ragforge serve kb/mini-balanced-v1 --transport http --auth-file secrets/shared-policy.json
# Explicit TLS listener, using an operator-managed certificate matching resource_url:
.\scripts\dev.ps1 run ragforge serve kb/mini-balanced-v1 --transport http --auth-file secrets/shared-policy.json --host 0.0.0.0 --port 8765 --tls-cert secrets/server.pem --tls-key secrets/server-key.pem
```

Both commands require a real policy. No default token, signing secret or permissive
policy ships with the project. Plain HTTP binds to loopback by default; binding a
non-loopback IP requires explicit TLS certificate and private key. A TLS proxy can
terminate an HTTPS resource URL with a loopback-only backend. Host must match the
configured resource authority; forwarding headers and environment proxies are not
trusted. The listener has one worker, at most 16 concurrent connections, serialized
engine/model calls, 5-second keepalive and bounded graceful shutdown.

## Bring an existing issuer and public keys

The server verifies **RS256** JWT access tokens against pinned local RSA public
keys (at least 2048 bits). It checks signature, known `kid`, exact issuer and single
string audience, required integer `iat`/`exp`, time validity and allowed subject.
Maximum token lifetime defaults to one hour, configurable up to 24 hours. Remote
key URLs, embedded keys and unsupported critical headers are rejected. It never
fetches JWKS, downloads keys, refreshes tokens or contacts the identity provider.
The access token audience is exactly `resource_url`, including `/mcp`, for both
REST and MCP requests. Required scope is `retrieval:read`.

Obtain a public signing JWKS from your existing identity provider through your
normal administrative workflow. The separate preparation helper accepts an
already-acquired **public** file and writes a new policy without network access:

```powershell
.\scripts\dev.ps1 run python scripts/prepare_shared_policy.py --jwks-file secrets/public-jwks.json --issuer https://identity.example.com/team --resource https://docs.example.com/mcp --collection mini --subject USER_SUBJECT --output secrets/shared-policy.json
.\scripts\dev.ps1 run ragforge schema shared-policy
```

The example issuer/resource names are placeholders, not configured services. Use
the exact issuer and subject claims your identity provider issues. The helper
creates no tokens or accounts. It rejects private, symmetric, weak and non-signing
keys. The policy schema is [shared-policy-v1.schema.json](../schemas/shared-policy-v1.schema.json).
Key/policy rotation applies after restarting the server; retain old public keys
only while their issued tokens should remain valid.

Each policy principal has a `subject`, one `collection_id`, and optional
`document_ids` (1..100 explicit stable source IDs). Omitting that list grants the
whole bound collection. Unknown collections/documents are rejected at startup.
Search applies document permissions before ranking; a caller cannot expand them
with filters. Context checks its source before fetching any neighboring text.
Collection counts are restricted to granted documents. Parallel clients keep
separate SDK authentication contexts. Separate tenants should use separate
processes/indexes; this initial adapter shares one collection and ranking corpus
statistics, with document filtering rather than an independent index per user.

## Endpoints and clients

| Route | Operation | Authentication |
|---|---|---|
| `POST /retrieve` | `RetrieveRequest` to `RetrievalResponse` | Bearer, read scope |
| `POST /context` | `FetchContextRequest` to `RetrievalResponse` | Bearer, read scope |
| `GET /collections` | Permitted collection/counts | Bearer, read scope |
| `GET /health` | Ready status and loaded build ID | Bearer, read scope |
| `GET /metadata` | Runtime/contract/build/capabilities | Bearer, read scope |
| `POST /mcp` | Same three read-only MCP tools, stateless HTTP | Bearer, read scope |
| `/.well-known/oauth-protected-resource/mcp` | Issuer/resource discovery | Public metadata |

MCP authentication/discovery uses the SDK resource-server implementation with
resource validation explicitly enabled. Signing in/token issuance remains with
your identity provider. See the [official SDK authorization guide](https://py.sdk.modelcontextprotocol.io/run/authorization/).
Both modern and handshake-era MCP clients are exercised in tests.

Set `RAGFORGE_ACCESS_TOKEN` in the client environment using your normal token
workflow. Tokens are never command-line arguments or saved in generated files:

```powershell
.\scripts\dev.ps1 run ragforge use --mode shared --endpoint https://docs.example.com --query rollback --search-method hybrid
.\scripts\dev.ps1 run ragforge context CHUNK_ID --mode shared --endpoint https://docs.example.com --collection mini
.\scripts\dev.ps1 run ragforge doctor --endpoint https://docs.example.com
```

`--token-env NAME` selects another explicit environment variable. `--ca-file PATH`
adds the operator's CA for a private TLS service; certificate and hostname
verification remain enabled. HTTP endpoints on non-loopback hosts are refused.
The client follows no redirects, ignores proxy environment variables, bounds
responses to 2 MiB and revalidates request-specific scope/output budgets. It does
not renew tokens automatically. Missing/expired tokens fail explicitly.

All data responses have `Cache-Control: no-store`. REST/MCP share a 64 KiB body
limit and a 10-second body-read deadline. Host/Origin allowlists apply before
routing, including REST. Invalid input returns generic errors without echoing
queries, tokens or source text. Access logging and inherited OpenTelemetry export
are disabled. The server never executes documents. TLS is transport protection;
server-side documents remain available to the operating-system service account.
See [official HTTP deployment guidance](https://py.sdk.modelcontextprotocol.io/run/deploy/).

## Verification and remaining work

Real loopback REST/MCP clients exercise minimal, exact and ANN bundles; scoped
parallel users; invalid issuer/audience/signature/expiry/headers; forbidden source
filters/context; modern/legacy protocols; CLI search/context/doctor; real TLS with
certificate validation; redirect/proxy credential isolation and response budgets.
Tests generate temporary identities/certificates; none is an operational issuer.

Operator version pointers and connection profiles are implemented below. The
[systemd example and restart/backup procedure](../deploy/README.md) are reviewable
host templates, not an installed/verified remote service. Actual multi-device
hosting and later SSH/cloud work remain separate; no production host is claimed.


## Prepare, activate and roll back local deployment state

`deploy` prepares files around an existing immutable bundle. It never starts a
server, copies data to another host, provisions resources or installs host/agent
settings. A required smoke query must return evidence in **every** supported
retrieval method (up to three hits, 4,000 characters). Optional
`--expected-document-id` requires that source among each method's results. The
query and returned text are never persisted in deployment files.

```powershell
.\scripts\dev.ps1 run ragforge deploy kb/mini-balanced-v1 --mode shared --output deployments/team --auth-file secrets/shared-policy.json --smoke-query rollback
.\scripts\dev.ps1 run ragforge serve --deployment deployments/team --transport http
.\scripts\dev.ps1 run ragforge use --mode shared --connection deployments/team/connection.json --query rollback
.\scripts\dev.ps1 run ragforge doctor --connection deployments/team/connection.json
.\scripts\dev.ps1 run ragforge activate kb/mini-balanced-v2 --deployment deployments/team --smoke-query rollback
# Explicitly restart the server, then confirm the new build ID with doctor.
.\scripts\dev.ps1 run ragforge rollback --deployment deployments/team --smoke-query rollback
# Explicitly restart again to serve the restored version.
```

Both version directories must already exist. Bundle contents are not rebuilt or
modified. Candidate hashes, collection identity, policy grants and actual smoke
queries are checked before an atomic `deployment.json` replacement. Concurrent
metadata writers are locked. Up to ten previous verified version references are
retained; source bundles are never deleted automatically. Rollback re-verifies
and re-tests its target, keeping the current pointer unchanged if that fails.

The running server keeps its startup snapshot until an explicit restart. On
startup, a deployment's expected build ID must match the verified artifact before
a listener opens. Registry paths describe one host and should be regenerated
when moving to another host. `serve.json` is a passive command array;
`connection.json` is a passive client profile with origin, token-environment name
and optional CA path. It contains no token. Relative CA paths resolve beside the
profile. The connection schema is [shared-connection-v1.schema.json](../schemas/shared-connection-v1.schema.json).

REST/MCP parity is also tested with the actual pretrained local E5 model for exact
and ANN bundles on both CI operating systems. Linux OS network isolation remains
a separate core CLI/stdio check; the HTTP tests deliberately use loopback sockets.
