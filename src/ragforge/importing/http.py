"""Bounded public HTTP GET with DNS pinning and normal TLS verification."""

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from threading import Timer
from typing import Any
from urllib.parse import urlsplit

from ragforge.core.web_sources import normalize_url

USER_AGENT = "RAGForgeDocImporter/0.1"


@dataclass(frozen=True)
class WebResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def public_addresses(host: str, port: int) -> list[tuple[Any, ...]]:
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("document host has no addresses")
    for row in addresses:
        ip = ipaddress.ip_address(row[4][0])
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise ValueError("URL import only connects to public Internet addresses")
    return addresses


def close_socket(stream: socket.socket) -> None:
    try:
        stream.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    stream.close()


class PublicHTTP:
    def get(self, url: str, *, max_bytes: int, timeout: float) -> WebResponse:
        url = normalize_url(url)
        parsed = urlsplit(url)
        assert parsed.hostname is not None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        # Resolve once, validate EVERY answer, and connect only to that exact address.
        addresses = public_addresses(parsed.hostname, port)
        deadline = time.monotonic() + timeout
        last: OSError | None = None
        for family, kind, protocol, _, address in addresses:
            stream = socket.socket(family, kind, protocol)
            current = [stream]
            timer = Timer(
                max(0.01, deadline - time.monotonic()),
                lambda current=current: close_socket(current[0]),
            )
            timer.daemon = True
            timer.start()
            connection = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)
            try:
                stream.settimeout(max(0.01, deadline - time.monotonic()))
                stream.connect(address)
                if parsed.scheme == "https":
                    tls = ssl.create_default_context().wrap_socket(
                        stream, server_hostname=parsed.hostname, do_handshake_on_connect=False
                    )
                    current[0] = tls
                    tls.do_handshake()
                    stream = tls
                connection.sock = stream
                target = parsed.path + ("?" + parsed.query if parsed.query else "")
                connection.request(
                    "GET",
                    target,
                    headers={
                        "Host": parsed.netloc,
                        "User-Agent": USER_AGENT,
                        "Accept-Encoding": "identity",
                        "Accept": (
                            "text/html,application/xhtml+xml,application/pdf,"
                            "text/plain,text/markdown"
                        ),
                        "Connection": "close",
                    },
                )
                response = connection.getresponse()
                headers = {k.lower(): v for k, v in response.getheaders()}
                if response.status != 200:
                    return WebResponse(response.status, headers, b"")
                if headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                    raise ValueError(
                        "compressed transfer unsupported; server ignored identity encoding"
                    )
                length = headers.get("content-length")
                if length is not None and (not length.isdecimal() or int(length) > max_bytes):
                    raise ValueError("web resource exceeds the byte limit")
                body = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("document request exceeded its I/O deadline")
                    stream.settimeout(remaining)
                    block = response.read1(min(65536, max_bytes - len(body) + 1))
                    if not block:
                        break
                    body.extend(block)
                    if len(body) > max_bytes:
                        raise ValueError("web resource exceeds the byte limit")
                if length is not None and len(body) != int(length):
                    raise ValueError("incomplete web response body")
                return WebResponse(response.status, headers, bytes(body))
            except OSError as error:
                last = error
            finally:
                timer.cancel()
                connection.close()
                close_socket(current[0])
            if time.monotonic() >= deadline:
                break
        raise OSError(f"could not download public document: {last}") from last
