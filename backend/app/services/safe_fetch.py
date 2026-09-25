"""SSRF-safe fetching of public web pages (spec sections 20-21).

URL validator -> domain policy -> DNS resolution -> IP policy (checked again at connect time,
so DNS rebinding cannot swap in an internal address) -> size/time-limited fetch ->
redirects re-validated hop by hop -> HTML to plain text.

The LLM never fetches anything itself; only this service does, and only for URLs a user
submitted as evidence.
"""
import ipaddress
import re
import socket
from html import unescape
from urllib.parse import urljoin, urlsplit

import httpcore

from ..core import config

ALLOWED_PORTS = {None, 80, 443}
MAX_REDIRECTS = 3
BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata", "instance-data"}
USER_AGENT = "IdentityEvidenceBot/1.0 (+evidence capture; respects robots on request)"


class FetchBlocked(ValueError):
    pass


def check_ip(ip: str):
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if not addr.is_global or addr.is_multicast or addr.is_reserved or str(addr) in ("169.254.169.254",):
        raise FetchBlocked(f"Address {addr} is not a public internet address")


def validate_url(url: str) -> tuple[str, int, str]:
    """Returns (host, port, scheme) or raises FetchBlocked."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise FetchBlocked("Only http and https URLs can be captured")
    if parts.username or parts.password:
        raise FetchBlocked("URLs with credentials are not allowed")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise FetchBlocked("URL has no host")
    if parts.port not in ALLOWED_PORTS:
        raise FetchBlocked("Only the standard ports 80 and 443 are allowed")
    if host in BLOCKED_HOSTS or host.endswith((".local", ".internal", ".localhost")):
        raise FetchBlocked(f"Host {host} is not allowed")
    if any(host == d or host.endswith("." + d) for d in config.FETCH_DENY_DOMAINS):
        raise FetchBlocked(f"Domain {host} is blocked by policy")
    try:
        check_ip(host)  # IP literal
    except ValueError as e:
        if isinstance(e, FetchBlocked):
            raise
    return host, parts.port or (443 if parts.scheme == "https" else 80), parts.scheme


def resolve_public(host: str, port: int) -> str:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise FetchBlocked(f"Cannot resolve {host}") from e
    ips = {i[4][0] for i in infos}
    for ip in ips:
        check_ip(ip)  # every answer must be public, or an attacker can race us to a private one
    return sorted(ips)[0]


class _PinnedBackend(httpcore.SyncBackend):
    """Resolves and validates at connect time and connects to the validated IP."""

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        ip = resolve_public(host, port)
        return super().connect_tcp(ip, port, timeout=timeout, local_address=local_address,
                                   socket_options=socket_options)


def fetch(url: str) -> dict:
    """Returns {final_url, status, content_type, body (bytes)}; raises FetchBlocked on policy violations."""
    timeouts = {"connect": config.FETCH_TIMEOUT, "read": config.FETCH_TIMEOUT, "write": config.FETCH_TIMEOUT,
                "pool": config.FETCH_TIMEOUT}
    with httpcore.ConnectionPool(network_backend=_PinnedBackend(), max_connections=2, retries=0) as pool:
        for _ in range(MAX_REDIRECTS + 1):
            validate_url(url)
            with pool.stream("GET", url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,*/*;q=0.5"},
                             extensions={"timeout": timeouts}) as resp:
                headers = {k.decode().lower(): v.decode(errors="replace") for k, v in resp.headers}
                if resp.status in (301, 302, 303, 307, 308) and "location" in headers:
                    url = urljoin(url, headers["location"])
                    continue
                body = bytearray()
                for chunk in resp.iter_stream():
                    body += chunk
                    if len(body) > config.FETCH_MAX_BYTES:
                        raise FetchBlocked(f"Page is larger than {config.FETCH_MAX_BYTES // 1024} KB")
                return {"final_url": url, "status": resp.status,
                        "content_type": headers.get("content-type", ""), "body": bytes(body)}
    raise FetchBlocked("Too many redirects")


_SCRIPT = re.compile(r"<(script|style|noscript|template|svg)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def html_to_text(html: str) -> tuple[str, str]:
    """(title, visible text). Content sanitizer: scripts/styles removed, tags stripped."""
    title = unescape(_TITLE.search(html).group(1)).strip() if _TITLE.search(html) else ""
    text = unescape(_TAG.sub(" ", _SCRIPT.sub(" ", html)))
    return title[:300], re.sub(r"\s+", " ", text).strip()
