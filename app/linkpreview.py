"""Best-effort title/image extraction from a listing URL (Open Graph tags).

Many real-estate portals block bots, so every failure is silent: the user can
always type the title and paste an image URL by hand.
"""
import ipaddress
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:title", "og:image", "twitter:title", "twitter:image") and a.get("content"):
                self.meta.setdefault(key, a["content"])
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = data.strip()


def _is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def fetch(url: str, timeout: float = 6.0) -> dict[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not _is_public(parsed.hostname):
        return {}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA}) as c:
            r = c.get(url)
            if r.status_code >= 400 or "html" not in r.headers.get("content-type", ""):
                return {}
            p = _MetaParser()
            p.feed(r.text[:500_000])
    except (httpx.HTTPError, ValueError):
        return {}
    title = p.meta.get("og:title") or p.meta.get("twitter:title") or p.title
    image = p.meta.get("og:image") or p.meta.get("twitter:image") or ""
    return {
        "title": unescape(title)[:200],
        "image_url": urljoin(str(r.url), image) if image else "",
    }
