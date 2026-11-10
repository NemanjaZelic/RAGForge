"""Explicit website acquisition and portable, offline URL provenance."""

import asyncio
import hashlib
import json
import socket
from pathlib import Path

import pytest

from ragforge.adapters.integration import create_integration
from ragforge.adapters.mcp import create_server
from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.verification import verify_bundle
from ragforge.core.contracts import FetchContextRequest, RetrieveRequest, SourceLocation
from ragforge.core.engine import BundleEngine
from ragforge.core.web_sources import normalize_url, read_web_sources
from ragforge.importing.http import WebResponse, public_addresses
from ragforge.importing.website import SiteOptions, import_site
from ragforge.quickstart import active_bundle, ready_documentation

ROOT = "https://docs.example.org/docs/"


def response(text, media="text/html; charset=utf-8", status=200):
    return WebResponse(status, {"content-type": media}, text.encode("utf-8"))


class Site:
    def __init__(self, pages=None, robots="User-agent: *\nDisallow: /docs/blocked.html\n"):
        self.calls = []
        self.pages = pages or {
            ROOT: response(
                "<h1>Retry rules</h1><p>The retry token expires after forty seconds.</p>"
                '<a href="guide.html#retry">Guide</a><a href="guide.html">duplicate</a>'
                '<a href="/other/">out</a><a href="https://external.example/">external</a>'
                '<a href="blocked.html">blocked</a><a href="image.png">asset</a>'
            ),
            ROOT + "guide.html": response(
                "<h1>Rollback</h1><p>Rollback requires the retry token.</p>"
            ),
        }
        self.robots = robots

    def get(self, url, *, max_bytes, timeout):
        self.calls.append(url)
        assert max_bytes > 0 and timeout > 0
        if url.endswith("/robots.txt"):
            return response(self.robots, "text/plain")
        return self.pages[url]


def options(**kw):
    return SiteOptions(delay=0, **kw)


def test_crawl_scope_robots_and_immutable_snapshot(tmp_path):
    site = Site(robots="User-agent: *\nDisallow: /docs/blocked.html\n")
    snap = import_site(ROOT, tmp_path / "snapshot", fetcher=site, options=options())
    assert snap.catalogue.complete
    assert {s.url for s in snap.catalogue.sources} == {ROOT, ROOT + "guide.html"}
    assert site.calls == ["https://docs.example.org/robots.txt", ROOT, ROOT + "guide.html"]
    for item in snap.catalogue.sources:
        assert (
            hashlib.sha256((snap.documents / item.source_path).read_bytes()).hexdigest()
            == item.content_sha256
        )
    assert read_web_sources(snap.provenance) == snap.catalogue
    assert (
        json.loads((snap.directory / "import-report.json").read_text())["skipped_outside_policy"]
        == 4
    )
    with pytest.raises(FileExistsError):
        import_site(ROOT, snap.directory, fetcher=site)


def test_limits_failures_redirects_and_encodings(tmp_path):
    snap = import_site(ROOT, tmp_path / "limited", fetcher=Site(), options=options(max_pages=1))
    assert not snap.catalogue.complete and "page limit" in snap.catalogue.issues[0]
    site = Site(
        {
            ROOT: response('<a href="bad.html">broken</a>'),
            ROOT + "bad.html": response("", status=503),
        }
    )
    assert not import_site(
        ROOT, tmp_path / "failed", fetcher=site, options=options()
    ).catalogue.complete
    site = Site({ROOT: WebResponse(302, {"location": "http://docs.example.org/docs/"}, b"")})
    with pytest.raises(ValueError, match="downgrade"):
        import_site(ROOT, tmp_path / "downgrade", fetcher=site, options=options())
    assert not (tmp_path / "downgrade").exists()
    site = Site(
        {
            ROOT: WebResponse(
                200,
                {"content-type": "text/plain; charset=windows-1252"},
                "Café retry".encode("cp1252"),
            )
        }
    )
    snap = import_site(ROOT, tmp_path / "encoded", fetcher=site, options=options(max_depth=0))
    source = snap.catalogue.sources[0]
    assert source.raw_sha256 != source.content_sha256
    assert (snap.documents / source.source_path).read_text(encoding="utf-8") == "Café retry"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://u:p@example.org/",
        "https://example.org/a b",
        "https://example.org/\\bad",
    ],
)
def test_bad_urls(url):
    with pytest.raises(ValueError):
        normalize_url(url)


@pytest.mark.parametrize(
    "addresses", [["127.0.0.1"], ["169.254.169.254"], ["93.184.216.34", "192.168.1.2"], ["::1"]]
)
def test_all_dns_answers_must_be_public(monkeypatch, addresses):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses
        ],
    )
    with pytest.raises(ValueError, match="public"):
        public_addresses("example.org", 443)


def test_import_build_engine_context_and_actual_mcp_are_offline(tmp_path, monkeypatch):
    snap = import_site(ROOT, tmp_path / "snapshot", fetcher=Site(), options=options())
    bundle = tmp_path / "bundle"
    manifest = build_bundle(snap.documents, bundle, profile="minimal", web_sources=snap.provenance)
    assert manifest.web_sources and verify_bundle(bundle) == manifest

    def no_network(*args, **kwargs):
        raise AssertionError("retrieval must be offline")

    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    original_connect = socket.socket.connect

    def local_only(stream, address):
        if address[0] not in {"127.0.0.1", "::1"}:
            no_network()
        return original_connect(stream, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
    engine = BundleEngine(bundle)
    request = RetrieveRequest(query="retry token")
    result = engine.retrieve(request)
    assert result.results and all(
        r.source.url in {ROOT, ROOT + "guide.html"} for r in result.results
    )
    first = result.results[0]
    context = engine.fetch_context(
        FetchContextRequest(collection_id=first.collection_id, chunk_id=first.chunk_id, neighbors=1)
    )
    assert context.results and all(r.source.url == first.source.url for r in context.results)
    integration = create_integration(bundle, tmp_path / "agent")
    meta = json.loads(
        (Path(integration["output"]) / integration["skill"])
        .parent.joinpath("references/collection.json")
        .read_text()
    )
    assert meta["website_snapshot"]["seed_url"] == ROOT

    async def mcp():
        from mcp import Client

        async with Client(create_server(bundle)) as client:
            call = await client.call_tool("search_docs", {"query": "retry token"})
            assert not call.is_error
            payload = call.structured_content
            assert payload["results"][0]["source"]["url"].startswith(ROOT)

    asyncio.run(mcp())
    # The catalogue itself is inventoried and tampering must fail before search.
    (bundle / manifest.web_sources).write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        BundleEngine(bundle)


def test_catalogue_must_match_sources_and_old_local_json_stays_stable(tmp_path):
    snap = import_site(ROOT, tmp_path / "snapshot", fetcher=Site(), options=options(max_depth=0))
    item = snap.catalogue.sources[0]
    (snap.documents / item.source_path).write_text("changed content")
    with pytest.raises(ValueError, match="provenance"):
        build_bundle(
            snap.documents, tmp_path / "bad", profile="minimal", web_sources=snap.provenance
        )
    assert "url" not in SourceLocation(path="local.txt").model_dump(mode="json")
    assert "url" not in SourceLocation(path="local.txt").model_dump_json()


def test_incomplete_site_does_not_replace_active_bundle(
    tmp_path, tiny_model, tiny_reranker, monkeypatch
):
    import ragforge.importing.website as website

    project = tmp_path / "project"
    project.mkdir()
    docs = project / "documents"
    docs.mkdir()
    (docs / "local.txt").write_text("retry token forty seconds")
    previous = ready_documentation(project, query_model=tiny_model, reranker=tiny_reranker)
    snap = import_site(ROOT, tmp_path / "partial", fetcher=Site(), options=options(max_pages=1))
    monkeypatch.setattr(website, "import_site", lambda *a, **kw: snap)
    with pytest.raises(ValueError, match="incomplete"):
        ready_documentation(project, url=ROOT, query_model=tiny_model, reranker=tiny_reranker)
    assert active_bundle(project) == previous
    current = ready_documentation(
        project, url=ROOT, allow_partial_site=True, query_model=tiny_model, reranker=tiny_reranker
    )
    assert current != previous and active_bundle(project) == current
    assert (
        BundleEngine(current).retrieve(RetrieveRequest(query="retry")).results[0].source.url == ROOT
    )


def test_http_pins_the_validated_ip_and_bounds_the_body(monkeypatch):
    import ragforge.importing.http as http

    calls = []

    class Stream:
        def settimeout(self, value):
            assert value > 0

        def connect(self, address):
            calls.append(("connect", address))

        def shutdown(self, *args):
            pass

        def close(self):
            pass

    class Reply:
        status = 200

        def __init__(self):
            self.parts = [b"hello", b""]

        def getheaders(self):
            return [("Content-Type", "text/plain"), ("Content-Length", "5")]

        def read1(self, count):
            return self.parts.pop(0)

    class Connection:
        def __init__(self, *args, **kwargs):
            self.sock = None

        def request(self, method, target, headers):
            calls.append((method, target, headers["Host"]))
            assert headers["Accept-Encoding"] == "identity"

        def getresponse(self):
            return Reply()

        def close(self):
            pass

    dns = []

    def resolve(*args, **kwargs):
        dns.append(args)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "socket", lambda *args: Stream())
    monkeypatch.setattr(http.http.client, "HTTPConnection", Connection)
    assert (
        http.PublicHTTP().get("http://example.org/docs/?v=1", max_bytes=10, timeout=3).body
        == b"hello"
    )
    assert len(dns) == 1 and calls == [
        ("connect", ("93.184.216.34", 80)),
        ("GET", "/docs/?v=1", "example.org"),
    ]
    with pytest.raises(ValueError, match="byte limit"):
        http.PublicHTTP().get("http://example.org/docs/", max_bytes=4, timeout=3)


def test_https_preserves_certificate_validation_and_original_sni(monkeypatch):
    import ssl

    import ragforge.importing.http as http

    events = []

    class Stream:
        def settimeout(self, value):
            pass

        def connect(self, address):
            events.append(address)

        def shutdown(self, *args):
            pass

        def close(self):
            pass

        def do_handshake(self):
            events.append("handshake")

    class Reply:
        status = 404

        def getheaders(self):
            return [("Content-Encoding", "gzip"), ("Content-Length", "99999999")]

    class Connection:
        def __init__(self, *args, **kwargs):
            self.sock = None

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Reply()

        def close(self):
            pass

    def wrap(context, stream, *, server_hostname, do_handshake_on_connect):
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        assert server_hostname == "docs.example.org" and not do_handshake_on_connect
        return stream

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(socket, "socket", lambda *args: Stream())
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap)
    monkeypatch.setattr(http.http.client, "HTTPConnection", Connection)
    result = http.PublicHTTP().get(ROOT + "robots.txt", max_bytes=1000, timeout=3)
    assert result.status == 404 and events == [("93.184.216.34", 443), "handshake"]


def test_denied_or_unavailable_robots_never_downloads_the_page(tmp_path):
    class Denied(Site):
        def get(self, url, **kwargs):
            self.calls.append(url)
            assert url.endswith("/robots.txt")
            return response("", status=403)

    site = Denied()
    with pytest.raises(ValueError, match="robots.txt disallows"):
        import_site(ROOT, tmp_path / "denied", fetcher=site, options=options())
    assert site.calls == ["https://docs.example.org/robots.txt"]
    assert not list(tmp_path.glob(".ragforge-site-*"))


def test_url_command_arguments_and_offline_snapshot_reuse(
    tmp_path, tiny_model, tiny_reranker, monkeypatch
):
    import ragforge.importing.website as website
    from ragforge.quickstart import main

    project = tmp_path / "project"
    project.mkdir()
    snap = import_site(ROOT, tmp_path / "saved", fetcher=Site(), options=options(max_depth=0))
    seen = []

    def acquire(url, output, *, options, progress):
        seen.append((url, options.max_pages, options.max_depth))
        return snap

    monkeypatch.setattr(website, "import_site", acquire)
    common = [
        "--project",
        str(project),
        "build",
        "--model",
        str(tiny_model),
        "--reranker",
        str(tiny_reranker),
    ]
    assert main([*common, "--url", ROOT, "--site-max-pages", "17", "--site-max-depth", "0"]) == 0
    assert seen == [(ROOT, 17, 0)]
    old = active_bundle(project)
    monkeypatch.setattr(
        website, "import_site", lambda *a, **kw: pytest.fail("saved snapshot must stay offline")
    )
    assert main([*common, str(snap.documents)]) == 0
    new = active_bundle(project)
    assert new != old
    assert BundleEngine(new).retrieve(RetrieveRequest(query="retry")).results[0].source.url == ROOT
    assert main([*common, str(snap.documents), "--url", ROOT]) == 2
    assert active_bundle(project) == new
