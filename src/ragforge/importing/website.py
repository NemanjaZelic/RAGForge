"""Explicit, bounded static-site acquisition; never called by retrieval."""

import hashlib
import http.client
import json
import posixpath
import shutil
import tempfile
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from ragforge.artifacts.builder import publish_new
from ragforge.core.source import is_link
from ragforge.core.web_sources import (
    WebSource,
    WebSources,
    decoded_path,
    normalize_url,
    url_origin,
)
from ragforge.importing.http import USER_AGENT, PublicHTTP, WebResponse


@dataclass(frozen=True)
class SiteOptions:
    max_pages: int = 100
    max_depth: int = 2
    max_file_bytes: int = 32 * 1024**2
    max_total_bytes: int = 512 * 1024**2
    timeout: float = 20.0
    max_elapsed: float = 600.0
    delay: float = 1.0

    def __post_init__(self) -> None:
        if type(self.max_pages) is not int or not 1 <= self.max_pages <= 1000:
            raise ValueError("site max_pages must be 1..1000")
        if type(self.max_depth) is not int or not 0 <= self.max_depth <= 10:
            raise ValueError("site max_depth must be 0..10")
        if (
            not 1 <= self.max_file_bytes <= 32 * 1024**2
            or not self.max_file_bytes <= self.max_total_bytes <= 512 * 1024**2
        ):
            raise ValueError("site byte limits exceed supported input capacity")
        if (
            not 0 < self.timeout <= 120
            or not 0 < self.max_elapsed <= 86400
            or not 0 <= self.delay <= 60
        ):
            raise ValueError("invalid site time limits")


class Fetcher(Protocol):
    def get(self, url: str, *, max_bytes: int, timeout: float) -> WebResponse: ...


class SkippedURL(ValueError):
    pass


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.base: str | None = None
        self.nofollow = False
        self.overflow = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "base" and self.base is None:
            self.base = values.get("href")
        if tag == "meta" and (values.get("name") or "").lower() == "robots":
            self.nofollow = self.nofollow or "nofollow" in {
                token.strip() for token in (values.get("content") or "").lower().split(",")
            }
        if (
            tag == "a"
            and values.get("href")
            and "nofollow" not in (values.get("rel") or "").lower().split()
        ):
            if len(self.hrefs) >= 10000:
                self.overflow = True
            else:
                self.hrefs.append(str(values["href"]))


@dataclass(frozen=True)
class SiteSnapshot:
    directory: Path
    catalogue: WebSources

    @property
    def documents(self) -> Path:
        return self.directory / "pages"

    @property
    def provenance(self) -> Path:
        return self.directory / "web-sources.json"


class Crawler:
    def __init__(
        self,
        options: SiteOptions,
        fetcher: Fetcher,
        progress: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        self.options, self.fetcher, self.progress = options, fetcher, progress
        self.started = time.monotonic()
        self.bytes = 0
        self.last: dict[str, float] = {}
        self.robots: dict[str, RobotFileParser] = {}
        self.origin = self.path = self.seed = ""
        self.skipped = 0

    def request(self, url: str, limit: int, delay: float = 0) -> WebResponse:
        origin = url_origin(url)
        wait = max(
            0.0, self.last.get(origin, 0) + max(delay, self.options.delay) - time.monotonic()
        )
        remaining = self.options.max_elapsed - (time.monotonic() - self.started)
        if remaining <= wait:
            raise TimeoutError("site import elapsed-time budget reached")
        if wait:
            time.sleep(wait)
        limit = min(limit, self.options.max_total_bytes - self.bytes)
        if limit < 1:
            raise ValueError("site total byte budget reached")
        self.last[origin] = time.monotonic()
        response = self.fetcher.get(
            url, max_bytes=limit, timeout=min(self.options.timeout, remaining - wait)
        )
        if len(response.body) > limit:
            raise ValueError("web response exceeded its byte limit")
        self.bytes += len(response.body)
        return response

    def policy(self, url: str) -> RobotFileParser:
        origin = url_origin(url)
        if origin not in self.robots:
            robots_url = origin + "/robots.txt"
            response = None
            for _ in range(6):
                response = self.request(robots_url, 512 * 1024)
                if response.status in {301, 302, 303, 307, 308}:
                    target = normalize_url(
                        urljoin(robots_url, response.headers.get("location", ""))
                    )
                    if (
                        urlsplit(robots_url).scheme == "https"
                        and urlsplit(target).scheme != "https"
                    ):
                        raise ValueError("robots redirect would downgrade HTTPS")
                    robots_url = target
                    continue
                break
            assert response is not None
            parser = RobotFileParser(origin + "/robots.txt")
            if response.status == 200:
                parser.parse(response.body.decode("utf-8-sig", errors="replace").splitlines())
            elif response.status in {401, 403}:
                parser.parse(["User-agent: *", "Disallow: /"])
            elif 400 <= response.status < 500 and response.status != 429:
                parser.parse(["User-agent: *", "Allow: /"])
            else:
                raise ValueError("robots.txt is unreachable or has too many redirects")
            self.robots[origin] = parser
        return self.robots[origin]

    def in_scope(self, url: str) -> bool:
        path = decoded_path(url)
        return url_origin(url) == self.origin and (
            path == decoded_path(self.seed)
            or path == self.path.rstrip("/")
            or path.startswith(self.path)
        )

    def document(self, url: str, *, initial: bool) -> tuple[str, WebResponse]:
        for _ in range(6):
            if not initial and not self.in_scope(url):
                raise SkippedURL("redirect is outside the chosen documentation scope")
            policy = self.policy(url)
            if not policy.can_fetch(USER_AGENT, url):
                raise SkippedURL("robots.txt disallows this URL")
            delay = float(policy.crawl_delay(USER_AGENT) or 0)
            rate = policy.request_rate(USER_AGENT)
            if rate is not None and rate.requests > 0:
                delay = max(delay, rate.seconds / rate.requests)
            response = self.request(url, self.options.max_file_bytes, delay)
            if response.status in {301, 302, 303, 307, 308}:
                target = normalize_url(urljoin(url, response.headers.get("location", "")))
                if target == url:
                    raise ValueError("missing or looping redirect location")
                if urlsplit(url).scheme == "https" and urlsplit(target).scheme != "https":
                    raise ValueError("document redirect would downgrade HTTPS")
                url = target
                continue
            if response.status != 200:
                raise ValueError(f"HTTP status {response.status}")
            return url, response
        raise ValueError("too many document redirects")


def decoded_document(response: WebResponse, url: str) -> tuple[bytes, str, str, Links | None]:
    header = Message()
    header["content-type"] = response.headers.get("content-type", "")
    media = header.get_content_type().lower()
    if media == "application/pdf":
        if not response.body.startswith(b"%PDF-"):
            raise ValueError("PDF response lacks a PDF signature")
        return response.body, "pdf", media, None
    if media not in {
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "text/markdown",
        "text/x-markdown",
    }:
        raise SkippedURL("unsupported document media type")
    charset = (header.get_content_charset() or "utf-8").lower()
    if charset not in {
        "utf-8",
        "utf8",
        "utf-8-sig",
        "us-ascii",
        "ascii",
        "iso-8859-1",
        "latin-1",
        "windows-1252",
        "cp1252",
    }:
        raise ValueError("unsupported text encoding; static UTF-8 documentation is preferred")
    text = response.body.decode("utf-8-sig" if charset in {"utf-8", "utf8"} else charset)
    links = None
    if media in {"text/html", "application/xhtml+xml"}:
        extension = "html"
        links = Links()
        links.feed(text)
        links.close()
    else:
        extension = (
            "md"
            if media in {"text/markdown", "text/x-markdown"}
            or urlsplit(url).path.lower().endswith(".md")
            else "txt"
        )
    return text.encode("utf-8"), extension, media, links


def import_site(
    url: str,
    output: Path,
    *,
    options: SiteOptions | None = None,
    fetcher: Fetcher | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> SiteSnapshot:
    options = options or SiteOptions()
    seed = normalize_url(url)
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("site snapshot output already exists; choose a new directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    parent = output.parent.resolve(strict=True)
    output = parent / output.name
    stage = Path(tempfile.mkdtemp(prefix=".ragforge-site-", dir=parent))
    pages = stage / "pages"
    pages.mkdir()
    crawler = Crawler(options, fetcher or PublicHTTP(), progress)
    queue = deque([(seed, 0)])
    discovered, completed = {seed}, set()
    records: list[WebSource] = []
    issues: list[str] = []
    indexed_bytes = 0
    try:
        while queue:
            if len(records) >= options.max_pages:
                issues.append("page limit reached while further in-scope URLs remain")
                break
            requested, depth = queue.popleft()
            try:
                actual, response = crawler.document(requested, initial=not records)
                if actual in completed:
                    continue
                encoded, extension, media, links = decoded_document(response, actual)
                if (
                    len(encoded) > options.max_file_bytes
                    or indexed_bytes + len(encoded) > options.max_total_bytes
                ):
                    raise ValueError("normalized document exceeds the source byte budget")
                if not records:
                    crawler.origin = url_origin(actual)
                    crawler.seed = actual
                    path = decoded_path(actual)
                    crawler.path = (
                        posixpath.dirname(path) + "/"
                        if posixpath.splitext(path)[1].lower()
                        in {".html", ".htm", ".pdf", ".md", ".txt"}
                        else path.rstrip("/") + "/"
                    )
                    if crawler.path == "//":
                        crawler.path = "/"
                name = hashlib.sha256(actual.encode()).hexdigest() + "." + extension
                (pages / name).write_bytes(encoded)
                indexed_bytes += len(encoded)
                records.append(
                    WebSource(
                        source_path=name,
                        url=actual,
                        content_sha256=hashlib.sha256(encoded).hexdigest(),
                        raw_sha256=hashlib.sha256(response.body).hexdigest(),
                        media_type=media,
                    )
                )
                completed.add(actual)
                if links is not None and not links.nofollow and depth < options.max_depth:
                    if links.overflow:
                        issues.append("link discovery limit reached on an HTML page")
                    base = actual
                    if links.base:
                        candidate = normalize_url(urljoin(actual, links.base))
                        if crawler.in_scope(candidate):
                            base = candidate
                    for href in links.hrefs:
                        try:
                            candidate = normalize_url(urljoin(base, href))
                            suffix = posixpath.splitext(urlsplit(candidate).path.lower())[1]
                            if not crawler.in_scope(candidate) or suffix not in {
                                "",
                                ".html",
                                ".htm",
                                ".pdf",
                                ".txt",
                                ".md",
                            }:
                                crawler.skipped += 1
                                continue
                            if candidate not in discovered:
                                if len(discovered) >= 10000:
                                    issues.append("total URL discovery limit reached")
                                    queue.clear()
                                    break
                                discovered.add(candidate)
                                queue.append((candidate, depth + 1))
                        except ValueError:
                            crawler.skipped += 1
                if progress:
                    progress(
                        {
                            "phase": "web",
                            "pages": len(records),
                            "queued": len(queue),
                            "downloaded_bytes": crawler.bytes,
                        }
                    )
            except SkippedURL as error:
                crawler.skipped += 1
                if not records:
                    issues.append(str(error))
            except (OSError, ValueError, http.client.HTTPException) as error:
                issues.append(f"{requested}: {type(error).__name__}: {error}")
                if not records or time.monotonic() - crawler.started >= options.max_elapsed:
                    break
        if not records:
            raise ValueError(
                "no supported documents imported; "
                + ("; ".join(issues[:1]) or "start URL is excluded")
            )
        catalogue = WebSources(
            seed_url=seed,
            fetched_at=datetime.now(UTC).isoformat(),
            max_pages=options.max_pages,
            max_depth=options.max_depth,
            complete=not issues,
            issues=issues[:10000],
            sources=records,
        )
        (stage / "web-sources.json").write_text(
            catalogue.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (stage / "import-report.json").write_text(
            json.dumps(
                {
                    "pages": len(records),
                    "downloaded_bytes": crawler.bytes,
                    "indexed_bytes": indexed_bytes,
                    "skipped_outside_policy": crawler.skipped,
                    "complete": catalogue.complete,
                    "issues": catalogue.issues,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        publish_new(stage, output)
        return SiteSnapshot(output, catalogue)
    finally:
        if stage.exists():
            if (
                stage.resolve().parent != parent
                or is_link(stage.lstat())
                or not stage.name.startswith(".ragforge-site-")
            ):
                raise ValueError("refusing cleanup outside owned site staging directory")
            shutil.rmtree(stage)
