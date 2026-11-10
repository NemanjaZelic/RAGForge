"""Client credentials and response boundaries against real redirecting HTTP servers."""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ragforge.core.contracts import RetrieveRequest
from ragforge.shared.client import SharedClient


@contextmanager
def endpoint(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()
        assert not thread.is_alive()


def test_redirect_and_environment_proxy_never_receive_bearer_credentials(monkeypatch):
    seen = []

    class Trap(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append("trap")
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    with endpoint(Trap) as target:

        class Redirect(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(self.headers.get("Authorization"))
                # Drain the POST before closing; unread bytes may reset a TCP
                # connection on Windows before the client receives the 307.
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(307)
                self.send_header("Location", target + "/retrieve")
                self.end_headers()

            def log_message(self, *args):
                pass

        with endpoint(Redirect) as source:
            monkeypatch.setenv("HTTP_PROXY", target)
            monkeypatch.setenv("http_proxy", target)
            monkeypatch.setenv("NO_PROXY", "")
            with pytest.raises(ValueError, match="HTTP 307"):
                SharedClient(source, "synthetic-bearer").retrieve(RetrieveRequest(query="alpha"))
    assert seen == ["Bearer synthetic-bearer"]


def test_client_rejects_valid_contract_that_exceeds_the_request_budget(monkeypatch):
    from ragforge.core.identity import document_id

    client = SharedClient("http://127.0.0.1:8765", "synthetic-bearer")
    payload = {
        "contract_version": "1",
        "results": [
            {
                "collection_id": "docs",
                "document_id": document_id("docs", "a.txt"),
                "chunk_id": "a" * 64,
                "text": "too much text",
                "source": {"path": "a.txt"},
                "rank_score": 1.0,
                "retrieval_method": "bm25",
            }
        ],
    }
    monkeypatch.setattr(client, "_request", lambda *a: json.dumps(payload).encode())
    with pytest.raises(ValueError, match="scope or budget"):
        client.retrieve(RetrieveRequest(query="alpha", max_output_chars=3))
    with pytest.raises(ValueError, match="scope or budget"):
        client.retrieve(RetrieveRequest(query="alpha", collection_id="other"))


def test_shared_client_rejects_plaintext_remote_credentials_and_missing_env(monkeypatch):
    for endpoint_url in (
        "http://remote.example",
        "https://user:pass@example.com",
        "https://example.com/?secret=value",
        "https://example.com/path",
    ):
        with pytest.raises(ValueError):
            SharedClient(endpoint_url, "synthetic-bearer")
    monkeypatch.delenv("RAGFORGE_ACCESS_TOKEN", raising=False)
    with pytest.raises(ValueError, match="bearer token"):
        SharedClient.from_environment("http://127.0.0.1:8765")
