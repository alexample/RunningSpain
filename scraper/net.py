"""Descargas educadas: respeta robots.txt, espera entre peticiones y reintenta."""
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

from . import config

_session = requests.Session()
_session.headers.update({
    "User-Agent": config.USER_AGENT,
    "Accept-Language": "es-ES,es;q=0.9,ca;q=0.6,en;q=0.5",
})
_last_hit: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
stats = {"requests": 0, "errors": 0, "blocked_by_robots": 0}


def domain(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _allowed(url: str) -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = _session.get(base + "/robots.txt", timeout=10)
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            else:
                rp = None  # sin robots.txt: se permite
        except requests.RequestException:
            rp = None
        _robots[base] = rp
    rp = _robots[base]
    return True if rp is None else rp.can_fetch(config.USER_AGENT, url)


def _wait(host: str) -> None:
    last = _last_hit.get(host)
    if last is not None:
        gap = time.monotonic() - last
        if gap < config.REQUEST_DELAY:
            time.sleep(config.REQUEST_DELAY - gap)
    _last_hit[host] = time.monotonic()


def get(url: str, binary: bool = False):
    """Devuelve (contenido, url_final, content_type) o (None, url, None) si falla."""
    if not url or not url.startswith(("http://", "https://")):
        return None, url, None
    if not _allowed(url):
        stats["blocked_by_robots"] += 1
        return None, url, None
    host = domain(url)
    for attempt in range(2):
        _wait(host)
        stats["requests"] += 1
        try:
            r = _session.get(url, timeout=config.TIMEOUT, allow_redirects=True)
        except requests.RequestException:
            stats["errors"] += 1
            continue
        if r.status_code in (429, 503) and attempt == 0:
            time.sleep(8)
            continue
        if r.status_code != 200:
            stats["errors"] += 1
            return None, r.url, None
        ctype = r.headers.get("content-type", "").lower()
        if binary or "pdf" in ctype:
            return r.content, r.url, ctype
        r.encoding = r.encoding or r.apparent_encoding
        return r.text, r.url, ctype
    return None, url, None


def probe(url: str) -> tuple[bool, str, bool]:
    """¿Abre el enlace? Devuelve (funciona, url_final, es_pdf). Solo lee el principio del archivo."""
    if not url or not url.startswith(("http://", "https://")):
        return False, url, False
    host = domain(url)
    for attempt in range(2):
        _wait(host)
        stats["requests"] += 1
        try:
            r = _session.get(url, timeout=config.TIMEOUT, allow_redirects=True, stream=True,
                             headers={"Referer": f"{urlparse(url).scheme}://{urlparse(url).netloc}/"})
            head = next(r.iter_content(2048), b"")
            r.close()
        except (requests.RequestException, StopIteration):
            stats["errors"] += 1
            continue
        if r.status_code in (429, 503) and attempt == 0:
            time.sleep(8)
            continue
        is_pdf = head.startswith(b"%PDF")
        if r.status_code >= 400:
            return False, r.url, False
        # un enlace «.pdf» que devuelve una página no es el documento
        if url.lower().split("?")[0].endswith(".pdf") and not is_pdf:
            return False, r.url, False
        return True, r.url, is_pdf
    return False, url, False
