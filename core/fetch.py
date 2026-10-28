"""Bounded fetching pinned to a validated IP, with TLS hostname verification."""
from datetime import datetime, timezone
import socket
import time
from urllib.parse import urlsplit, urljoin

from bs4 import BeautifulSoup
import urllib3

from core.urls import clean_url, public_ip

MAX_BYTES = 512 * 1024
MAX_REDIRECTS = 3


def public_addresses(host, port):
    answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(item[4][0] for item in answers))
    if not addresses:
        raise ValueError("No DNS addresses")
    for address in addresses:
        if not public_ip(address):
            raise ValueError("Blocked non-public DNS address")
    return addresses


def fetch_html(url, timeout=10):
    deadline = time.monotonic() + timeout
    for _ in range(MAX_REDIRECTS + 1):
        url = clean_url(url)
        parsed = urlsplit(url)
        port = 443 if parsed.scheme == "https" else 80
        address = public_addresses(parsed.hostname, port)[0]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Fetch deadline exceeded")
        options = dict(host=address, port=port, maxsize=1, retries=False,
                       timeout=urllib3.Timeout(connect=min(3, remaining), read=min(3, remaining)))
        if parsed.scheme == "https":
            pool = urllib3.HTTPSConnectionPool(**options, server_hostname=parsed.hostname,
                                              assert_hostname=parsed.hostname, cert_reqs="CERT_REQUIRED")
        else:
            pool = urllib3.HTTPConnectionPool(**options)
        response = None
        try:
            path = parsed.path + ("?" + parsed.query if parsed.query else "")
            response = pool.urlopen("GET", path, headers={"Host": parsed.netloc,
                "User-Agent": "OmniAgent/1.0", "Accept": "text/html", "Accept-Encoding": "identity"},
                redirect=False, preload_content=False, retries=False)
            if response.status in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            if response.status != 200 or "text/html" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("Not an HTML success response")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("Compressed responses are not accepted")
            if int(response.headers.get("Content-Length", "0")) > MAX_BYTES:
                raise ValueError("Page too large")
            body = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Fetch deadline exceeded")
                connection = response.connection
                if connection and connection.sock:
                    connection.sock.settimeout(min(3, remaining))
                chunk = response.read1(min(32768, MAX_BYTES + 1 - len(body)), decode_content=False)
                if not chunk:
                    return bytes(body).decode("utf-8", errors="replace"), url
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError("Page too large")
        finally:
            if response:
                response.close()
            pool.close()
    raise ValueError("Too many redirects")


def page_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()
    meta = soup.find("meta", attrs={"name": "description"})
    description = meta.get("content", "") if meta else ""
    return " ".join((description + " " + soup.get_text(" ", strip=True)).split())[:6000]

